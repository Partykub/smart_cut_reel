"""Render the final 9:16 MP4 from ``render_plan.json`` using FFmpeg.

Phase 1 supports two modes:

- ``static_crop``: single keyframe → one ffmpeg pass with ``crop`` + ``scale``.
- ``smooth_crop``: keyframe-per-window → multiple ffmpeg passes followed by
  concat demuxer and audio mux.

Phase 2 adds ``smooth_crop_with_cuts``: each ``segment`` from ``render_plan.
segments`` becomes a trim window with its own per-segment crop keyframes; all
trimmed/cropped clips are concatenated and the source audio is sliced to match
the kept ranges so audio stays in sync with video after dead-air removal.
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

        render_mode = str(plan.get("render_mode") or "static_crop")
        ffmpeg_config = self._ffmpeg_config(context)

        crop_w_e = _even_dimension(crop_w)
        crop_h_e = _even_dimension(crop_h)
        tw = _even_dimension(target_w)
        th = _even_dimension(target_h)

        with tempfile.TemporaryDirectory() as tmp:
            src_path = Path(tmp) / "source.mp4"
            out_path = Path(tmp) / "out.mp4"
            overlay_path = Path(tmp) / "source_overlay.mp4"
            src_path.write_bytes(source_bytes)

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
                )
            elif render_mode == "smooth_crop":
                self._render_smooth_segments(
                    src_path=src_path,
                    out_path=out_path,
                    plan=plan,
                    crop_w_e=crop_w_e,
                    crop_h_e=crop_h_e,
                    target_w=tw,
                    target_h=th,
                    ffmpeg_config=ffmpeg_config,
                )
            else:
                self._render_static_crop(
                    src_path=src_path,
                    out_path=out_path,
                    keyframes=keyframes,
                    crop_w_e=crop_w_e,
                    crop_h_e=crop_h_e,
                    target_w=tw,
                    target_h=th,
                    ffmpeg_config=ffmpeg_config,
                    source_bytes=source_bytes,
                    audio_policy=str(plan.get("audio_policy") or "copy_if_possible_else_aac"),
                )

            self._render_source_overlay(
                src_path=src_path,
                out_path=overlay_path,
                plan=plan,
                raw_tracks=raw_tracks,
                source_bytes=source_bytes,
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
        }
        defaults.update(context.request.config)
        return defaults

    def _artifact_manifest(self, context: ServiceContext) -> dict[str, Any]:
        key = context.request.inputs.get("artifact_manifest")
        if not key or not context.exists(key):
            raise ValueError("request is missing artifact_manifest for ffmpeg_renderer")
        return context.read_json(key)

    def _raw_tracks(self, context: ServiceContext, artifact_manifest: dict[str, Any]) -> dict[str, Any]:
        raw_entry = artifact_manifest.get("artifacts", {}).get("body_tracks_raw", {})
        raw_key = raw_entry.get("object_key") if isinstance(raw_entry, dict) else None
        if not isinstance(raw_key, str) or not context.exists(raw_key):
            raise ValueError("artifact_manifest is missing body_tracks_raw for ffmpeg_renderer")
        return context.read_json(raw_key)

    def _render_static_crop(
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
        source_bytes: bytes,
        audio_policy: str,
    ) -> None:
        first = keyframes[0]
        cx = max(0, int(round(float(first.get("x") or 0.0))))
        cy = max(0, int(round(float(first.get("y") or 0.0))))

        probe = probe_video_bytes(source_bytes)
        video_codec = str(ffmpeg_config.get("video_codec") or "libx264")
        audio_codec = str(ffmpeg_config.get("audio_codec") or "aac")

        vf = f"crop={crop_w_e}:{crop_h_e}:{cx}:{cy},scale={target_w}:{target_h}"

        cmd: list[str] = [
            "ffmpeg",
            "-y",
            "-i",
            str(src_path),
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
            "-movflags",
            "+faststart",
        ]

        if _has_audio_stream(probe):
            if audio_policy == "aac_transcode":
                cmd.extend(["-c:a", audio_codec, "-b:a", "192k"])
            else:
                cmd.extend(["-c:a", "copy"])
        else:
            cmd.append("-an")

        cmd.append(str(out_path))
        self._run_ffmpeg(cmd)

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
        windows: list[tuple[float, float, dict[str, Any]]] = []
        for index in range(len(sorted_kf)):
            t_start = float(sorted_kf[index].get("t") or 0.0)
            t_end = float(sorted_kf[index + 1].get("t") or duration) if index + 1 < len(sorted_kf) else duration
            windows.append((t_start, t_end, sorted_kf[index]))

        single_window = [
            {
                "source_start": 0.0,
                "source_end": duration,
                "windows": windows,
            }
        ]

        self._render_keep_segments(
            src_path=src_path,
            out_path=out_path,
            keep_segments=single_window,
            crop_w_e=crop_w_e,
            crop_h_e=crop_h_e,
            target_w=target_w,
            target_h=target_h,
            ffmpeg_config=ffmpeg_config,
            audio_policy=str(plan.get("audio_policy") or "copy_if_possible_else_aac"),
            mux_full_audio=True,
        )

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
    ) -> None:
        video_codec = str(ffmpeg_config.get("video_codec") or "libx264")
        audio_codec = str(ffmpeg_config.get("audio_codec") or "aac")
        temp_root = out_path.parent

        sub_segments: list[Path] = []
        audio_segments: list[Path] = []
        probe = probe_video_bytes(src_path.read_bytes())
        has_audio = _has_audio_stream(probe)

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

            if not mux_full_audio and has_audio:
                audio_seg_path = temp_root / f"keep_{keep_index:04d}.audio.m4a"
                seg_duration = float(keep["source_end"]) - keep_start
                audio_args = ["-c:a", audio_codec, "-b:a", "192k"] if audio_policy == "aac_transcode" else ["-c:a", "copy"]
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{keep_start:.6f}",
                    "-i",
                    str(src_path),
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
                audio_policy=audio_policy,
                audio_codec=audio_codec,
                probe=probe,
            )
            return

        if not audio_segments or not has_audio:
            shutil.move(video_only_path, out_path)
            return

        concat_audio_path = temp_root / "audio_only.m4a"
        self._concat_audio(audio_segments, concat_audio_path)

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

    def _render_source_overlay(
        self,
        *,
        src_path: Path,
        out_path: Path,
        plan: dict[str, Any],
        raw_tracks: dict[str, Any],
        source_bytes: bytes,
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

        temp_video_path = out_path.with_suffix(".video.mp4")
        writer = cv2.VideoWriter(
            str(temp_video_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (frame_width, frame_height),
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
        track_times = [float(track.get("t") or 0.0) for track in tracks]

        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            current_t = frame_index / fps
            track = self._track_for_time(tracks, track_times, current_t)
            crop_box = self._crop_box_for_time(
                keyframes=sorted_keyframes,
                t=current_t,
                crop_width=crop_width,
                crop_height=crop_height,
                frame_width=frame_width,
                frame_height=frame_height,
            )

            self._draw_overlay(frame, track=track, crop_box=crop_box)
            writer.write(frame)
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
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
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
        x = int(round(float(bbox.get("x") or 0.0)))
        y = int(round(float(bbox.get("y") or 0.0)))
        width = int(round(float(bbox.get("w") or 0.0)))
        height = int(round(float(bbox.get("h") or 0.0)))
        if width <= 0 or height <= 0:
            return

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
    ) -> None:
        if not _has_audio_stream(probe):
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
            str(src_path),
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
