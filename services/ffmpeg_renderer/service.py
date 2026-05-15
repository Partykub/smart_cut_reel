"""Render the final 9:16 MP4 from ``render_plan.json`` using FFmpeg.

``smooth_crop`` renders a continuous reframed timeline by decoding the source
video frame-by-frame, applying the planned crop in memory, and remuxing audio.

``smooth_crop_with_cuts`` renders one or more kept source ranges, each with its
own per-segment crop keyframes; all trimmed/cropped clips are concatenated and
the audio is sliced to match so A/V stays in sync after dead-air removal.
"""

from __future__ import annotations

import bisect
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2

from services.common.media import probe_video_bytes
from services.common.runtime import RunResponse
from services.common.runtime import ServiceContext


def _even_dimension(value: int) -> int:
    return max(2, (max(0, value) // 2) * 2)


def _has_audio_stream(probe: dict[str, Any]) -> bool:
    streams = probe.get("streams", [])
    if not isinstance(streams, list):
        return False
    return any(isinstance(s, dict) and s.get("codec_type") == "audio" for s in streams)


def _wav_file_has_audio(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 44
    except OSError:
        return False


_VALID_RENDER_MODES = frozenset({"smooth_crop", "smooth_crop_with_cuts"})


class FFmpegRendererService:
    service_id = "ffmpeg_renderer"

    def run(self, context: ServiceContext) -> RunResponse:
        artifact_manifest = self._artifact_manifest(context)
        render_entry = artifact_manifest.get("artifacts", {}).get("render_plan", {})
        plan_key = render_entry.get("object_key") if isinstance(render_entry, dict) else None
        if not isinstance(plan_key, str) or not context.exists(plan_key):
            raise ValueError("artifact_manifest is missing render_plan for ffmpeg_renderer")

        plan = context.read_json(plan_key)
        raw_tracks = self._raw_tracks(context, artifact_manifest)
        source_key = plan.get("source_video", {}).get("object_key")
        if not isinstance(source_key, str) or not context.exists(source_key):
            raise ValueError("render_plan is missing valid source_video.object_key")

        source_bytes = context.read_bytes(source_key)
        target = plan.get("target_resolution") or {}
        target_w = int(target.get("width") or 0)
        target_h = int(target.get("height") or 0)
        if target_w <= 0 or target_h <= 0:
            raise ValueError("render_plan must include positive target_resolution")

        crop_plan = plan.get("crop_plan") or {}
        crop_w = int(crop_plan.get("crop_width") or 0)
        crop_h = int(crop_plan.get("crop_height") or 0)
        keyframes = crop_plan.get("keyframes") or []
        if crop_w <= 0 or crop_h <= 0:
            raise ValueError("render_plan crop_plan must include crop dimensions")
        if not isinstance(keyframes, list) or not keyframes:
            raise ValueError("render_plan crop_plan must include keyframes")

        render_mode = str(plan.get("render_mode") or "smooth_crop")
        if render_mode not in _VALID_RENDER_MODES:
            allowed = ", ".join(sorted(_VALID_RENDER_MODES))
            raise ValueError(f"Unsupported render_mode '{render_mode}'. Allowed: {allowed}.")
        ffmpeg_config = self._ffmpeg_config(context)

        crop_w_e = _even_dimension(crop_w)
        crop_h_e = _even_dimension(crop_h)
        tw = _even_dimension(target_w)
        th = _even_dimension(target_h)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "source.mp4"
            out_path = tmp_path / "out.mp4"
            overlay_path = tmp_path / "source_overlay.mp4"
            src_path.write_bytes(source_bytes)

            audio_src_path = self._prepare_output_audio_source(
                plan=plan,
                context=context,
                temp_root=tmp_path,
                fallback_video_path=src_path,
            )
            source_probe = probe_video_bytes(source_bytes)
            source_has_audio = _has_audio_stream(source_probe)

            if render_mode == "smooth_crop_with_cuts":
                self._render_with_cuts(
                    src_path=src_path,
                    out_path=out_path,
                    plan=plan,
                    crop_w_e=crop_w_e,
                    crop_h_e=crop_h_e,
                    target_w=tw,
                    target_h=th,
                    ffmpeg_config=ffmpeg_config,
                    audio_src_path=audio_src_path,
                    source_has_audio_stream=source_has_audio,
                )
            else:
                self._render_smooth_segments(
                    src_path=src_path,
                    out_path=out_path,
                    plan=plan,
                    crop_w_e=crop_w_e,
                    crop_h_e=crop_h_e,
                    target_w=tw,
                    target_h=th,
                    ffmpeg_config=ffmpeg_config,
                    audio_src_path=audio_src_path,
                    source_has_audio_stream=source_has_audio,
                )

            self._render_source_overlay(
                src_path=src_path,
                out_path=overlay_path,
                plan=plan,
                raw_tracks=raw_tracks,
                source_bytes=source_bytes,
                ffmpeg_config=ffmpeg_config,
            )

            output_bytes = out_path.read_bytes()
            overlay_bytes = overlay_path.read_bytes()

        out_key = context.expected_output_key("final_9x16")
        overlay_key = context.expected_output_key("source_overlay")
        context.write_bytes(out_key, output_bytes, content_type="video/mp4")
        context.write_bytes(overlay_key, overlay_bytes, content_type="video/mp4")
        return RunResponse(
            service_id=self.service_id,
            outputs={"final_9x16": out_key, "source_overlay": overlay_key},
        )

    def _ffmpeg_config(self, context: ServiceContext) -> dict[str, Any]:
        defaults = {
            "video_codec": "libx264",
            "audio_codec": "aac",
            "audio_transition": "crossfade",
            "audio_transition_seconds": 0.02,
            "overlay_max_width": 0,
            "overlay_max_height": 0,
            "overlay_fps_cap": 0.0,
            "overlay_video_codec": "libx264",
            "overlay_preset": "ultrafast",
            "overlay_crf": 32,
        }
        defaults.update(context.request.config)
        return defaults

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        key = context.request.inputs.get("artifact_manifest")
        if not key or not context.exists(key):
            raise ValueError("request is missing artifact_manifest for ffmpeg_renderer")
        return context.read_json(key)

    def _prepare_output_audio_source(
        self,
        *,
        plan: dict[str, Any],
        context: ServiceContext,
        temp_root: Path,
        fallback_video_path: Path,
    ) -> Path:
        output_audio = plan.get("output_audio") or {}
        mode = str(output_audio.get("source") or "source_video")
        if mode == "source_video":
            return fallback_video_path
        if mode != "external_wav":
            raise ValueError(f"Unsupported render_plan output_audio.source '{mode}'")
        object_key = output_audio.get("object_key")
        if not isinstance(object_key, str) or not object_key:
            raise ValueError("render_plan output_audio.object_key is required for external_wav")
        if not context.exists(object_key):
            raise ValueError(f"output_audio object_key does not exist: {object_key}")
        wav_path = temp_root / "output_master_audio.wav"
        wav_path.write_bytes(context.read_bytes(object_key))
        return wav_path

    def _raw_tracks(self, context: ServiceContext, artifact_manifest: dict[str, Any]) -> dict[str, Any]:
        raw_entry = artifact_manifest.get("artifacts", {}).get("body_tracks_raw", {})
        raw_key = raw_entry.get("object_key") if isinstance(raw_entry, dict) else None
        if not isinstance(raw_key, str) or not context.exists(raw_key):
            return {"tracks": []}
        return context.read_json(raw_key)

    def _render_smooth_segments(
        self,
        *,
        src_path: Path,
        out_path: Path,
        plan: dict[str, Any],
        crop_w_e: int,
        crop_h_e: int,
        target_w: int,
        target_h: int,
        ffmpeg_config: dict[str, Any],
        audio_src_path: Path,
        source_has_audio_stream: bool,
    ) -> None:
        crop_plan = plan.get("crop_plan") or {}
        keyframes = crop_plan.get("keyframes") or []
        meta = plan.get("metadata") or {}
        duration = float(meta.get("duration") or 0.0)
        if duration <= 0:
            raise ValueError("smooth_crop requires metadata.duration")

        sorted_kf: list[dict[str, Any]] = sorted(
            keyframes,
            key=lambda k: float(k.get("t") or 0.0),
        )
        self._render_smooth_video_frames(
            src_path=src_path,
            out_path=out_path,
            keyframes=sorted_kf,
            crop_w_e=crop_w_e,
            crop_h_e=crop_h_e,
            target_w=target_w,
            target_h=target_h,
            ffmpeg_config=ffmpeg_config,
            audio_policy=str(plan.get("audio_policy") or "copy_if_possible_else_aac"),
            audio_src_path=audio_src_path,
            source_has_audio_stream=source_has_audio_stream,
        )

    def _render_smooth_video_frames(
        self,
        *,
        src_path: Path,
        out_path: Path,
        keyframes: list[dict[str, Any]],
        crop_w_e: int,
        crop_h_e: int,
        target_w: int,
        target_h: int,
        ffmpeg_config: dict[str, Any],
        audio_policy: str,
        audio_src_path: Path,
        source_has_audio_stream: bool,
    ) -> None:
        capture = cv2.VideoCapture(str(src_path))
        if not capture.isOpened():
            raise ValueError("failed to open source video for smooth crop rendering")

        frame_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if frame_width <= 0 or frame_height <= 0 or fps <= 0:
            capture.release()
            raise ValueError("source video has invalid dimensions or fps for smooth crop rendering")

        temp_video_path = out_path.with_suffix(".video.mp4")
        writer = cv2.VideoWriter(
            str(temp_video_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (target_w, target_h),
        )
        if not writer.isOpened():
            capture.release()
            raise ValueError("failed to create smooth crop video writer")

        sorted_keyframes = sorted(
            [keyframe for keyframe in keyframes if isinstance(keyframe, dict)],
            key=lambda keyframe: float(keyframe.get("t") or 0.0),
        )
        keyframe_frames = [int(keyframe.get("frame_index") or 0) for keyframe in sorted_keyframes]
        keyframe_times = [float(keyframe.get("t") or 0.0) for keyframe in sorted_keyframes]

        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            current_t = frame_index / fps
            crop_x, crop_y, crop_width, crop_height = self._crop_box_for_frame(
                keyframes=sorted_keyframes,
                keyframe_frames=keyframe_frames,
                keyframe_times=keyframe_times,
                frame_index=frame_index,
                t=current_t,
                crop_width=crop_w_e,
                crop_height=crop_h_e,
                frame_width=frame_width,
                frame_height=frame_height,
            )

            cropped = frame[crop_y:crop_y + crop_height, crop_x:crop_x + crop_width]
            if cropped.size == 0:
                capture.release()
                writer.release()
                raise ValueError("smooth crop rendering produced an empty frame crop")

            rendered = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_AREA)
            writer.write(rendered)
            frame_index += 1

        capture.release()
        writer.release()

        self._finalize_smooth_video(
            temp_video_path=temp_video_path,
            src_path=src_path,
            out_path=out_path,
            ffmpeg_config=ffmpeg_config,
            audio_policy=audio_policy,
            audio_src_path=audio_src_path,
            source_has_audio_stream=source_has_audio_stream,
        )

    def _finalize_smooth_video(
        self,
        *,
        temp_video_path: Path,
        src_path: Path,
        out_path: Path,
        ffmpeg_config: dict[str, Any],
        audio_policy: str,
        audio_src_path: Path,
        source_has_audio_stream: bool,
    ) -> None:
        video_codec = str(ffmpeg_config.get("video_codec") or "libx264")
        audio_codec = str(ffmpeg_config.get("audio_codec") or "aac")
        use_external_wav = audio_src_path != src_path
        has_audio = source_has_audio_stream if not use_external_wav else _wav_file_has_audio(audio_src_path)

        cmd: list[str] = [
            "ffmpeg",
            "-y",
            "-i",
            str(temp_video_path),
        ]
        if has_audio:
            cmd.extend(["-i", str(audio_src_path), "-map", "0:v:0", "-map", "1:a:0", "-shortest"])
        else:
            cmd.append("-an")

        cmd.extend(
            [
                "-c:v",
                video_codec,
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ]
        )
        if has_audio:
            if audio_policy == "aac_transcode" or use_external_wav:
                cmd.extend(["-c:a", audio_codec, "-b:a", "192k"])
            else:
                cmd.extend(["-c:a", "copy"])

        cmd.append(str(out_path))
        self._run_ffmpeg(cmd)

    def _render_with_cuts(
        self,
        *,
        src_path: Path,
        out_path: Path,
        plan: dict[str, Any],
        crop_w_e: int,
        crop_h_e: int,
        target_w: int,
        target_h: int,
        ffmpeg_config: dict[str, Any],
        audio_src_path: Path,
        source_has_audio_stream: bool,
    ) -> None:
        segments = plan.get("segments") or []
        if not isinstance(segments, list) or not segments:
            raise ValueError("smooth_crop_with_cuts requires a non-empty segments list in render_plan")

        crop_plan = plan.get("crop_plan") or {}
        sorted_global_kf = sorted(
            crop_plan.get("keyframes") or [],
            key=lambda k: float(k.get("t") or 0.0),
        )

        keep_segments: list[dict[str, Any]] = []
        for segment in segments:
            seg_start = float(segment.get("source_start") or 0.0)
            seg_end = float(segment.get("source_end") or 0.0)
            if seg_end <= seg_start:
                continue

            seg_keyframes = segment.get("crop_keyframes") or []
            if not seg_keyframes:
                seg_keyframes = _keyframes_for_window(sorted_global_kf, seg_start, seg_end)
            windows = _windows_from_segment_keyframes(seg_keyframes, seg_end - seg_start)
            keep_segments.append(
                {
                    "source_start": seg_start,
                    "source_end": seg_end,
                    "windows": windows,
                }
            )

        if not keep_segments:
            raise ValueError("smooth_crop_with_cuts collapsed all segments to zero duration")

        self._render_keep_segments(
            src_path=src_path,
            out_path=out_path,
            keep_segments=keep_segments,
            crop_w_e=crop_w_e,
            crop_h_e=crop_h_e,
            target_w=target_w,
            target_h=target_h,
            ffmpeg_config=ffmpeg_config,
            audio_policy=str(plan.get("audio_policy") or "copy_if_possible_else_aac"),
            mux_full_audio=False,
            audio_src_path=audio_src_path,
            source_has_audio_stream=source_has_audio_stream,
        )

    def _render_keep_segments(
        self,
        *,
        src_path: Path,
        out_path: Path,
        keep_segments: list[dict[str, Any]],
        crop_w_e: int,
        crop_h_e: int,
        target_w: int,
        target_h: int,
        ffmpeg_config: dict[str, Any],
        audio_policy: str,
        mux_full_audio: bool,
        audio_src_path: Path,
        source_has_audio_stream: bool,
    ) -> None:
        video_codec = str(ffmpeg_config.get("video_codec") or "libx264")
        audio_codec = str(ffmpeg_config.get("audio_codec") or "aac")
        transition = str(ffmpeg_config.get("audio_transition") or "crossfade").lower()
        transition_seconds = float(ffmpeg_config.get("audio_transition_seconds", 0.0))
        if transition_seconds <= 0 or transition == "none":
            transition = "none"
        temp_root = out_path.parent

        sub_segments: list[Path] = []
        audio_segments: list[Path] = []
        probe = probe_video_bytes(src_path.read_bytes())
        use_external_wav = audio_src_path != src_path
        has_audio = (
            source_has_audio_stream if not use_external_wav else _wav_file_has_audio(audio_src_path)
        )
        effective_audio_policy = "aac_transcode" if use_external_wav else audio_policy
        segment_durations = [
            max(0.0, float(seg["source_end"]) - float(seg["source_start"]))
            for seg in keep_segments
        ]
        min_segment_duration = min(segment_durations) if segment_durations else 0.0
        crossfade_seconds = min(transition_seconds, max(0.0, min_segment_duration / 2.0))
        use_crossfade = (
            (not mux_full_audio)
            and has_audio
            and transition == "crossfade"
            and crossfade_seconds > 0
            and len(keep_segments) > 1
        )

        for keep_index, keep in enumerate(keep_segments):
            keep_start = float(keep["source_start"])
            for window_index, (rel_start, rel_end, kf) in enumerate(keep["windows"]):
                seg_path = temp_root / f"keep_{keep_index:04d}_win_{window_index:04d}.mp4"
                window_duration = max(0.001, rel_end - rel_start)
                source_window_start = keep_start + rel_start

                cx = max(0, int(round(float(kf.get("x") or 0.0))))
                cy = max(0, int(round(float(kf.get("y") or 0.0))))
                vf = f"crop={crop_w_e}:{crop_h_e}:{cx}:{cy},scale={target_w}:{target_h}"

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{source_window_start:.6f}",
                    "-i",
                    str(src_path),
                    "-t",
                    f"{window_duration:.6f}",
                    "-vf",
                    vf,
                    "-c:v",
                    video_codec,
                    "-preset",
                    "fast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    str(seg_path),
                ]
                self._run_ffmpeg(cmd)
                sub_segments.append(seg_path)

            if not mux_full_audio and has_audio and not use_crossfade:
                audio_seg_path = temp_root / f"keep_{keep_index:04d}.audio.m4a"
                seg_duration = float(keep["source_end"]) - keep_start
                audio_args = (
                    ["-c:a", audio_codec, "-b:a", "192k"]
                    if effective_audio_policy == "aac_transcode"
                    else ["-c:a", "copy"]
                )
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{keep_start:.6f}",
                    "-i",
                    str(audio_src_path),
                    "-t",
                    f"{seg_duration:.6f}",
                    "-vn",
                    *audio_args,
                    str(audio_seg_path),
                ]
                self._run_ffmpeg(cmd)
                audio_segments.append(audio_seg_path)

        if not sub_segments:
            raise ValueError("renderer produced no video sub-segments")

        video_only_path = temp_root / "video_only.mp4"
        self._concat_video(sub_segments, video_only_path)

        if mux_full_audio:
            shutil.move(video_only_path, out_path)
            self._mux_audio_if_needed(
                src_path=src_path,
                video_path=out_path,
                audio_policy=effective_audio_policy,
                audio_codec=audio_codec,
                probe=probe,
                audio_src_path=audio_src_path,
            )
            return

        if not has_audio:
            shutil.move(video_only_path, out_path)
            return

        concat_audio_path = temp_root / "audio_only.m4a"
        if use_crossfade:
            self._render_crossfaded_audio(
                audio_src_path=audio_src_path,
                out_path=concat_audio_path,
                keep_segments=keep_segments,
                fade_seconds=crossfade_seconds,
                audio_codec=audio_codec,
            )
        elif audio_segments:
            self._concat_audio(audio_segments, concat_audio_path)
        else:
            shutil.move(video_only_path, out_path)
            return

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_only_path),
            "-i",
            str(concat_audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            "-c:v",
            "copy",
            "-c:a",
            audio_codec,
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        self._run_ffmpeg(cmd)

    def _concat_video(self, segments: list[Path], out_path: Path) -> None:
        if len(segments) == 1:
            shutil.copy2(segments[0], out_path)
            return

        list_path = out_path.parent / f"{out_path.stem}_concat.txt"
        list_path.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p in segments),
            encoding="utf-8",
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(out_path),
        ]
        self._run_ffmpeg(cmd)

    def _concat_audio(self, segments: list[Path], out_path: Path) -> None:
        if len(segments) == 1:
            shutil.copy2(segments[0], out_path)
            return

        list_path = out_path.parent / f"{out_path.stem}_concat.txt"
        list_path.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p in segments),
            encoding="utf-8",
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(out_path),
        ]
        self._run_ffmpeg(cmd)

    def _render_crossfaded_audio(
        self,
        *,
        audio_src_path: Path,
        out_path: Path,
        keep_segments: list[dict[str, Any]],
        fade_seconds: float,
        audio_codec: str,
    ) -> None:
        if len(keep_segments) < 2:
            raise ValueError("crossfade requires at least two segments")

        filters: list[str] = []
        for index, seg in enumerate(keep_segments):
            seg_start = float(seg["source_start"])
            seg_end = float(seg["source_end"])
            pre_pad = fade_seconds / 2.0 if index > 0 else 0.0
            post_pad = fade_seconds / 2.0 if index < len(keep_segments) - 1 else 0.0
            trim_start = max(0.0, seg_start - pre_pad)
            trim_end = max(trim_start, seg_end + post_pad)
            filters.append(
                f"[0:a]atrim=start={trim_start:.6f}:end={trim_end:.6f},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )

        prev = "a0"
        for index in range(1, len(keep_segments)):
            out = f"a{index}_x"
            filters.append(
                f"[{prev}][a{index}]acrossfade=d={fade_seconds:.6f}:c1=tri:c2=tri[{out}]"
            )
            prev = out

        filter_complex = ";".join(filters)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_src_path),
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{prev}]",
            "-c:a",
            audio_codec,
            "-b:a",
            "192k",
            str(out_path),
        ]
        self._run_ffmpeg(cmd)

    def _render_source_overlay(
        self,
        *,
        src_path: Path,
        out_path: Path,
        plan: dict[str, Any],
        raw_tracks: dict[str, Any],
        source_bytes: bytes,
        ffmpeg_config: dict[str, Any],
    ) -> None:
        capture = cv2.VideoCapture(str(src_path))
        if not capture.isOpened():
            raise ValueError("failed to open source video for overlay rendering")

        frame_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or plan.get("metadata", {}).get("fps") or 0.0)
        if frame_width <= 0 or frame_height <= 0:
            capture.release()
            raise ValueError("source video has invalid dimensions for overlay rendering")
        if fps <= 0:
            capture.release()
            raise ValueError("source video has invalid fps for overlay rendering")

        overlay_width, overlay_height, overlay_fps, frame_stride = _overlay_render_spec(
            frame_width=frame_width,
            frame_height=frame_height,
            fps=fps,
            max_width=int(ffmpeg_config.get("overlay_max_width") or 0),
            max_height=int(ffmpeg_config.get("overlay_max_height") or 0),
            fps_cap=float(ffmpeg_config.get("overlay_fps_cap") or 0.0),
        )
        scale_x = overlay_width / frame_width
        scale_y = overlay_height / frame_height

        temp_video_path = out_path.with_suffix(".video.mp4")
        writer = cv2.VideoWriter(
            str(temp_video_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            overlay_fps,
            (overlay_width, overlay_height),
        )
        if not writer.isOpened():
            capture.release()
            raise ValueError("failed to create overlay video writer")

        crop_plan = plan.get("crop_plan") or {}
        crop_width = int(crop_plan.get("crop_width") or 0)
        crop_height = int(crop_plan.get("crop_height") or 0)
        keyframes = crop_plan.get("keyframes") or []
        if crop_width <= 0 or crop_height <= 0 or not isinstance(keyframes, list) or not keyframes:
            capture.release()
            writer.release()
            raise ValueError("render_plan crop_plan is incomplete for overlay rendering")

        sorted_keyframes = sorted(
            [keyframe for keyframe in keyframes if isinstance(keyframe, dict)],
            key=lambda keyframe: float(keyframe.get("t") or 0.0),
        )
        tracks = [track for track in raw_tracks.get("tracks", []) if isinstance(track, dict)]
        keyframe_frames = [int(keyframe.get("frame_index") or 0) for keyframe in sorted_keyframes]
        keyframe_times = [float(keyframe.get("t") or 0.0) for keyframe in sorted_keyframes]
        track_frames = [int(track.get("frame_index") or 0) for track in tracks]
        track_times = [float(track.get("t") or 0.0) for track in tracks]

        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            current_t = frame_index / fps
            if frame_index % frame_stride != 0:
                frame_index += 1
                continue

            track = self._track_for_frame(
                tracks,
                track_frames=track_frames,
                track_times=track_times,
                frame_index=frame_index,
                t=current_t,
            )
            crop_box = self._crop_box_for_frame(
                keyframes=sorted_keyframes,
                keyframe_frames=keyframe_frames,
                keyframe_times=keyframe_times,
                frame_index=frame_index,
                t=current_t,
                crop_width=crop_width,
                crop_height=crop_height,
                frame_width=frame_width,
                frame_height=frame_height,
            )

            if overlay_width != frame_width or overlay_height != frame_height:
                overlay_frame = cv2.resize(
                    frame,
                    (overlay_width, overlay_height),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                overlay_frame = frame

            scaled_track = _scale_track_for_overlay(track, scale_x=scale_x, scale_y=scale_y)
            scaled_crop_box = _scale_crop_box_for_overlay(
                crop_box,
                scale_x=scale_x,
                scale_y=scale_y,
            )

            self._draw_overlay(overlay_frame, track=scaled_track, crop_box=scaled_crop_box)
            writer.write(overlay_frame)
            frame_index += 1

        capture.release()
        writer.release()

        self._encode_overlay_for_web(
            src_path=src_path,
            silent_video_path=temp_video_path,
            out_path=out_path,
            audio_policy=str(plan.get("audio_policy") or "copy_if_possible_else_aac"),
            audio_codec="aac",
            probe=probe_video_bytes(source_bytes),
            ffmpeg_config=ffmpeg_config,
        )

    def _encode_overlay_for_web(
        self,
        *,
        src_path: Path,
        silent_video_path: Path,
        out_path: Path,
        audio_policy: str,
        audio_codec: str,
        probe: dict[str, Any],
        ffmpeg_config: dict[str, Any],
    ) -> None:
        cmd: list[str] = [
            "ffmpeg",
            "-y",
            "-i",
            str(silent_video_path),
        ]

        if _has_audio_stream(probe):
            cmd.extend([
                "-i",
                str(src_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
            ])
        else:
            cmd.append("-an")

        cmd.extend([
            "-c:v",
            str(ffmpeg_config.get("overlay_video_codec") or "libx264"),
            "-preset",
            str(ffmpeg_config.get("overlay_preset") or "ultrafast"),
            "-crf",
            str(int(ffmpeg_config.get("overlay_crf") or 32)),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ])

        if _has_audio_stream(probe):
            if audio_policy == "aac_transcode":
                cmd.extend(["-c:a", audio_codec, "-b:a", "192k"])
            else:
                cmd.extend(["-c:a", "copy"])

        cmd.append(str(out_path))
        self._run_ffmpeg(cmd)

    def _track_for_time(
        self,
        tracks: list[dict[str, Any]],
        track_times: list[float],
        t: float,
    ) -> dict[str, Any] | None:
        if not track_times:
            return None

        index = bisect.bisect_right(track_times, t) - 1
        if index < 0:
            return tracks[0]
        return tracks[index]

    def _track_for_frame(
        self,
        tracks: list[dict[str, Any]],
        *,
        track_frames: list[int],
        track_times: list[float],
        frame_index: int,
        t: float,
    ) -> dict[str, Any] | None:
        if track_frames:
            index = bisect.bisect_right(track_frames, frame_index) - 1
            if index >= 0:
                return tracks[index]
            if tracks:
                return tracks[0]

        return self._track_for_time(tracks, track_times, t)

    def _crop_box_for_time(
        self,
        *,
        keyframes: list[dict[str, Any]],
        t: float,
        crop_width: int,
        crop_height: int,
        frame_width: int,
        frame_height: int,
    ) -> tuple[int, int, int, int]:
        keyframe_times = [float(keyframe.get("t") or 0.0) for keyframe in keyframes]
        index = max(0, bisect.bisect_right(keyframe_times, t) - 1)
        keyframe = keyframes[index]

        x = int(round(float(keyframe.get("x") or 0.0)))
        y = int(round(float(keyframe.get("y") or 0.0)))
        x = max(0, min(x, max(0, frame_width - crop_width)))
        y = max(0, min(y, max(0, frame_height - crop_height)))
        return x, y, crop_width, crop_height

    def _crop_box_for_frame(
        self,
        *,
        keyframes: list[dict[str, Any]],
        keyframe_frames: list[int],
        keyframe_times: list[float],
        frame_index: int,
        t: float,
        crop_width: int,
        crop_height: int,
        frame_width: int,
        frame_height: int,
    ) -> tuple[int, int, int, int]:
        if keyframe_frames:
            index = max(0, bisect.bisect_right(keyframe_frames, frame_index) - 1)
            keyframe = keyframes[index]
            x = int(round(float(keyframe.get("x") or 0.0)))
            y = int(round(float(keyframe.get("y") or 0.0)))
            x = max(0, min(x, max(0, frame_width - crop_width)))
            y = max(0, min(y, max(0, frame_height - crop_height)))
            return x, y, crop_width, crop_height

        return self._crop_box_for_time(
            keyframes=keyframes,
            t=t,
            crop_width=crop_width,
            crop_height=crop_height,
            frame_width=frame_width,
            frame_height=frame_height,
        )

    def _draw_overlay(
        self,
        frame: Any,
        *,
        track: dict[str, Any] | None,
        crop_box: tuple[int, int, int, int],
    ) -> None:
        crop_x, crop_y, crop_width, crop_height = crop_box
        frame_height, frame_width = frame.shape[:2]
        line_thickness = max(2, min(frame_width, frame_height) // 240)

        cv2.rectangle(
            frame,
            (crop_x, crop_y),
            (crop_x + crop_width, crop_y + crop_height),
            (0, 165, 255),
            line_thickness * 2,
        )
        self._draw_label(frame, "planned crop", crop_x, max(24, crop_y - 10), (0, 165, 255))

        if not track or track.get("missing"):
            return

        bbox = track.get("bbox") or {}
        body_bbox = track.get("body_bbox") or {}
        face_bbox = track.get("face_bbox") or {}
        x = int(round(float(bbox.get("x") or 0.0)))
        y = int(round(float(bbox.get("y") or 0.0)))
        width = int(round(float(bbox.get("w") or 0.0)))
        height = int(round(float(bbox.get("h") or 0.0)))
        if width <= 0 or height <= 0:
            return

        body_x = int(round(float(body_bbox.get("x") or 0.0)))
        body_y = int(round(float(body_bbox.get("y") or 0.0)))
        body_width = int(round(float(body_bbox.get("w") or 0.0)))
        body_height = int(round(float(body_bbox.get("h") or 0.0)))
        if body_width > 0 and body_height > 0:
            cv2.rectangle(frame, (body_x, body_y), (body_x + body_width, body_y + body_height), (80, 220, 100), line_thickness)
            self._draw_label(frame, "body roi", body_x, max(24, body_y - 10), (80, 220, 100))

        face_x = int(round(float(face_bbox.get("x") or 0.0)))
        face_y = int(round(float(face_bbox.get("y") or 0.0)))
        face_width = int(round(float(face_bbox.get("w") or 0.0)))
        face_height = int(round(float(face_bbox.get("h") or 0.0)))
        if face_width > 0 and face_height > 0:
            cv2.rectangle(frame, (face_x, face_y), (face_x + face_width, face_y + face_height), (255, 210, 80), line_thickness)
            self._draw_label(frame, "face bbox", face_x, max(24, face_y - 10), (255, 210, 80))

        cv2.rectangle(frame, (x, y), (x + width, y + height), (80, 220, 100), line_thickness)
        label = str(track.get("source") or "person")
        confidence = track.get("confidence")
        if isinstance(confidence, (int, float)):
            label = f"{label} {confidence:.2f}"
        self._draw_label(frame, label, x, max(24, y - 10), (80, 220, 100))

    def _draw_label(
        self,
        frame: Any,
        text: str,
        x: int,
        y: int,
        color: tuple[int, int, int],
    ) -> None:
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.5, min(frame.shape[1], frame.shape[0]) / 900)
        thickness = max(1, int(round(font_scale * 2)))
        (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
        top_left = (x, max(0, y - text_height - baseline - 6))
        bottom_right = (x + text_width + 8, y)
        cv2.rectangle(frame, top_left, bottom_right, (18, 18, 18), -1)
        cv2.putText(
            frame,
            text,
            (x + 4, y - 4),
            font,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

    def _mux_audio_if_needed(
        self,
        *,
        src_path: Path,
        video_path: Path,
        audio_policy: str,
        audio_codec: str,
        probe: dict[str, Any],
        audio_src_path: Path | None = None,
    ) -> None:
        audio_in = audio_src_path if audio_src_path is not None else src_path
        use_external = audio_src_path is not None and audio_src_path != src_path
        if not use_external and not _has_audio_stream(probe):
            return
        if use_external and not _wav_file_has_audio(audio_in):
            return

        tmp_audio_out = video_path.with_suffix(".muxed.mp4")
        if audio_policy == "aac_transcode":
            audio_args = ["-c:a", audio_codec, "-b:a", "192k"]
        else:
            audio_args = ["-c:a", "copy"]

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_in),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            "-c:v",
            "copy",
            *audio_args,
            str(tmp_audio_out),
        ]
        self._run_ffmpeg(cmd)
        shutil.move(tmp_audio_out, video_path)

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed"
            raise ValueError(detail)


def _overlay_render_spec(
    *,
    frame_width: int,
    frame_height: int,
    fps: float,
    max_width: int,
    max_height: int,
    fps_cap: float,
) -> tuple[int, int, float, int]:
    if frame_width <= 0 or frame_height <= 0 or fps <= 0:
        raise ValueError("overlay render spec requires positive dimensions and fps")

    width_limit = max_width if max_width > 0 else frame_width
    height_limit = max_height if max_height > 0 else frame_height
    scale = min(width_limit / frame_width, height_limit / frame_height, 1.0)

    overlay_width = _even_dimension(int(round(frame_width * scale)))
    overlay_height = _even_dimension(int(round(frame_height * scale)))

    capped_fps = min(fps, fps_cap) if fps_cap > 0 else fps
    frame_stride = max(1, int(round(fps / max(capped_fps, 1e-6))))
    overlay_fps = fps / frame_stride
    return overlay_width, overlay_height, overlay_fps, frame_stride


def _scale_crop_box_for_overlay(
    crop_box: tuple[int, int, int, int],
    *,
    scale_x: float,
    scale_y: float,
) -> tuple[int, int, int, int]:
    crop_x, crop_y, crop_width, crop_height = crop_box
    return (
        int(round(crop_x * scale_x)),
        int(round(crop_y * scale_y)),
        max(1, int(round(crop_width * scale_x))),
        max(1, int(round(crop_height * scale_y))),
    )


def _scale_track_for_overlay(
    track: dict[str, Any] | None,
    *,
    scale_x: float,
    scale_y: float,
) -> dict[str, Any] | None:
    if track is None:
        return None

    scaled_track = dict(track)
    bbox = track.get("bbox")
    if isinstance(bbox, dict):
        scaled_track["bbox"] = {
            "x": round(float(bbox.get("x") or 0.0) * scale_x, 2),
            "y": round(float(bbox.get("y") or 0.0) * scale_y, 2),
            "w": round(float(bbox.get("w") or 0.0) * scale_x, 2),
            "h": round(float(bbox.get("h") or 0.0) * scale_y, 2),
        }
    body_bbox = track.get("body_bbox")
    if isinstance(body_bbox, dict):
        scaled_track["body_bbox"] = {
            "x": round(float(body_bbox.get("x") or 0.0) * scale_x, 2),
            "y": round(float(body_bbox.get("y") or 0.0) * scale_y, 2),
            "w": round(float(body_bbox.get("w") or 0.0) * scale_x, 2),
            "h": round(float(body_bbox.get("h") or 0.0) * scale_y, 2),
        }
    face_bbox = track.get("face_bbox")
    if isinstance(face_bbox, dict):
        scaled_track["face_bbox"] = {
            "x": round(float(face_bbox.get("x") or 0.0) * scale_x, 2),
            "y": round(float(face_bbox.get("y") or 0.0) * scale_y, 2),
            "w": round(float(face_bbox.get("w") or 0.0) * scale_x, 2),
            "h": round(float(face_bbox.get("h") or 0.0) * scale_y, 2),
        }
    return scaled_track


def _windows_from_segment_keyframes(
    keyframes: list[dict[str, Any]],
    segment_duration: float,
) -> list[tuple[float, float, dict[str, Any]]]:
    """Convert per-segment crop keyframes into ``(rel_start, rel_end, kf)`` windows."""
    if not keyframes:
        return [(0.0, segment_duration, {"x": 0.0, "y": 0.0})]

    sorted_kf = sorted(keyframes, key=lambda k: float(k.get("t") or 0.0))
    windows: list[tuple[float, float, dict[str, Any]]] = []
    for index in range(len(sorted_kf)):
        rel_start = float(sorted_kf[index].get("t") or 0.0)
        if index + 1 < len(sorted_kf):
            rel_end = float(sorted_kf[index + 1].get("t") or segment_duration)
        else:
            rel_end = segment_duration
        if rel_end > rel_start:
            windows.append((rel_start, rel_end, sorted_kf[index]))

    if not windows:
        windows.append((0.0, segment_duration, sorted_kf[0]))
    return windows


def _keyframes_for_window(
    keyframes: list[dict[str, Any]],
    start: float,
    end: float,
) -> list[dict[str, Any]]:
    if not keyframes:
        return []

    inside = [kf for kf in keyframes if start <= float(kf.get("t") or 0.0) <= end]
    rebased = [
        {**kf, "t": round(float(kf.get("t") or 0.0) - start, 6)}
        for kf in inside
    ]
    if rebased and rebased[0]["t"] > 0.0:
        rebased.insert(0, {**rebased[0], "t": 0.0})
    if not rebased:
        nearest = min(keyframes, key=lambda kf: abs(float(kf.get("t") or 0.0) - start))
        rebased = [{**nearest, "t": 0.0}]
    return rebased
