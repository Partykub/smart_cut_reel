# smart_cut_reel

The **smooth vertical reframe** preset converts one 16:9 source into a 9:16 output with subject-aware smooth reframing.
The **dead-air** preset adds an audio chain (extract → VAD → cut planning) before vision and uses trim+crop+concat rendering.
The **audio-quality** preset adds enhancement + Silero VAD + faster-whisper ASR + optional filler-word cuts on top of dead-air.

## Current Status

- P1-A01 through P1-H03 / P1-B03 completed (Phase 1 baseline shipped).
- **Dead-air preset** (`pipeline_id = reframe_16x9_to_9x16_dead_air`, 12 steps) shipped: contracts accept `schema_version 1.0.0` and `2.0.0`; artifacts `extracted_audio`, `vad_segments`, `cut_plan`; dead-air services plus `compiler_render_mode = smooth_crop_with_cuts` with per-segment audio.
- **Audio-quality preset** (`pipeline_id = reframe_16x9_to_9x16_audio_quality`, 14 steps, `schema_version 3.0.0`) shipped: `services/audio_enhancement/`, `services/transcription/`, Silero VAD v5, filler-word cuts when `enabled_features.remove_filler_words` is on.

## Source Of Truth

- `Phase 1 Todo - 16x9 to 9x16 Smooth Reframe.md`: main planning doc and task board.
- `contracts/CONTRACTS.md`: shared contract rules, MinIO layout, manifest lifecycle, and artifact registry keys.
- `contracts/*.schema.json`: JSON Schemas for the three Phase 1 manifests.
- `contracts/examples/`: sample manifests for created, running, and completed states.
- `orchestrator/README.md`: implementation notes for the current Orchestrator package.

## Implemented So Far

### Contracts

- Phase 1 manifest schemas are in `contracts/job_manifest.schema.json`, `contracts/artifact_manifest.schema.json`, and `contracts/service_status.schema.json`.
- Artifact registry keys and pipeline step IDs are fixed and should not be renamed ad hoc.
- `artifact_manifest.json` is success-only state. In-progress execution stays in `service_status.json`.

### Orchestrator Package

- `orchestrator/path_resolver.py`: canonical object-key resolution for inputs, manifests, artifacts, outputs, and logs.
- `orchestrator/object_store.py`: filesystem-backed object store for tests and a MinIO-backed implementation for real usage.
- `orchestrator/manifest_manager.py`: schema-validated read/write helpers for manifests and status updates.
- `orchestrator/artifact_helper.py`: higher-level helpers for source uploads, artifact uploads, artifact reads, and artifact listing.
- `orchestrator/service.py`: create-job, get-status, and run-job service layer.
- `orchestrator/api.py`: FastAPI app factory exposing `POST /jobs`, `GET /jobs/{job_id}/status`, and `POST /jobs/{job_id}/run`.
- `orchestrator/pipeline_runner.py`: configurable HTTP pipeline runner for P1-A04 plus the mock fallback runner for local development.

### Downstream Services

- `services/validation/`: validates source input, target output config, and basic media readability.
- `services/media_metadata/`: probes source media with `ffprobe` and writes `metadata.json`.
- `services/proxy_frame_sampling/`: creates `proxy.mp4` and `sampled_frames.json` from source media.
- `services/body_detection/`: runs YOLO person detection on proxy frames with GPU-first inference and CPU fallback, then falls back to centered tracks when detections are missing.
- `services/track_interpolation/`: fills short gaps, applies hold/center fallback, and suppresses large outlier jumps.
- `services/reframe_planning/`: converts interpolated tracks into clamped 9:16 crop keyframes.
- `services/easing_smoothing/`: smooths raw reframe keyframes with easing, dead-zone handling, and bounded motion.
- `services/render_plan_compiler/`: builds `artifacts/render_plan.json` from metadata + `reframe_plan_smooth.json` (and, for Phase 2, `cut_plan.json`). Supports `compiler_render_mode` ∈ {`static_crop`, `smooth_crop`, `smooth_crop_with_cuts`}.
- `services/ffmpeg_renderer/`: renders `outputs/final_9x16.mp4` via FFmpeg. `static_crop` uses the first keyframe; `smooth_crop` slices windows between keyframes, concatenates, then muxes audio; `smooth_crop_with_cuts` does the same per keep-segment and slices the source audio to match (so dead-air removal stays A/V-synced).
- `services/audio_extraction/`: decodes the source audio track to mono PCM 16-bit WAV (default 16 kHz) and emits `artifacts/extracted_audio.wav`.
- `services/audio_enhancement/` (Phase 3): runs an FFmpeg filter chain (`highpass` → `afftdn` denoise → `loudnorm` EBU R128 to -16 LUFS / -1.5 dBTP by default) on `extracted_audio.wav` and emits `artifacts/enhanced_audio.wav`. On FFmpeg failure it copies the source audio through and emits a warning so the pipeline still proceeds.
- `services/voice_activity_detection/`: segments the timeline into `speech` / `silence` runs. `model: energy` is the Phase 2 default; `model: silero_v4` (Phase 3 default) loads the bundled Silero VAD v5 ONNX weights via `silero-vad` + `onnxruntime` (cached once per process). `audio_source` selects between `extracted_audio`, `enhanced_audio`, or `enhanced_audio_or_extracted` (fallback). Emits `artifacts/vad_segments.json`.
- `services/transcription/` (Phase 3): runs `faster-whisper` with word-level timestamps, restricted to the speech intervals from `vad_segments.json` so silence is skipped. Detects filler words from a configurable Thai + English dictionary (with surrounding-silence padding rule) and emits `artifacts/transcript.json`. Models are loaded lazily and cached per process; on model failure it emits an empty transcript so the rest of the pipeline still completes.
- `services/dead_air_cut_planning/`: turns the VAD timeline into `keep_segments` honoring `silence_threshold_seconds`, `keep_padding_before/after`, and `min_keep_segment_seconds`. When `enabled_features.remove_filler_words` is `true` and `transcript.json` is present, also subtracts filler-word intervals (with `filler_padding_before/after`) from the keep segments and reports `removed_filler_seconds` / `filler_word_count` in the plan metrics. When `enabled_features.remove_dead_air` is `false`, emits an identity plan so the renderer reuses Phase 1 behavior unchanged.

## Local Setup

Use a local virtual environment for Python work in this repo.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

To enable the real HTTP runner, configure service URLs before starting the Orchestrator. Phase 2 adds three audio services on ports 8019–8021; Phase 3 adds two more on ports 8022–8023:

```bash
export ORCHESTRATOR_SERVICE_ENDPOINTS='{
	"validation": "http://validation:8000",
	"media_metadata": "http://media-metadata:8000",
	"audio_extraction": "http://audio-extraction:8000",
	"audio_enhancement": "http://audio-enhancement:8000",
	"voice_activity_detection": "http://voice-activity-detection:8000",
	"transcription": "http://transcription:8000",
	"dead_air_cut_planning": "http://dead-air-cut-planning:8000",
	"proxy_frame_sampling": "http://proxy-frame-sampling:8000",
	"body_detection": "http://body-detection:8000",
	"track_interpolation": "http://track-interpolation:8000",
	"reframe_planning": "http://reframe-planning:8000",
	"easing_smoothing": "http://easing-smoothing:8000",
	"render_plan_compiler": "http://render-plan-compiler:8000",
	"ffmpeg_renderer": "http://ffmpeg-renderer:8000"
}'
export ORCHESTRATOR_MINIO_BUCKET='smart-cut'
export BODY_DETECTION_YOLO_MODEL='yolov8m.pt'
```

If `ORCHESTRATOR_SERVICE_ENDPOINTS` is not set, the API keeps using `MockPipelineRunner` so local development still works before every downstream service exists.

`services/body_detection/` now expects Ultralytics YOLO weights. By default it uses `yolov8m.pt`, prefers CUDA when available, and falls back to CPU automatically. Set `BODY_DETECTION_YOLO_MODEL` or `job_manifest.service_config.body_detection.model_path` to a local weights path if you do not want runtime downloads.

### Run the full HTTP pipeline locally (real `final_9x16.mp4`)

Requires **ffmpeg** and **ffprobe** on your PATH.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/start_local_stack.sh
```

This starts every microservice (Phase 1 ports `8010–8018` + Phase 2 ports `8019–8021` + Phase 3 ports `8022–8023`) and the orchestrator on **`http://127.0.0.1:8000`**, using `SMART_CUT_OBJECT_STORE_ROOT` (default: `.orchestrator-data/` under the repo). Press **Ctrl+C** to stop every process.

If you want to avoid the first Phase 3 job stalling on model download, prefetch the transcription model before running jobs:

```bash
# Optional: set model / compute_type first (defaults: small + int8)
export TRANSCRIPTION_WARMUP_MODEL=small
export TRANSCRIPTION_WARMUP_COMPUTE_TYPE=int8

# One-shot prefetch
./scripts/prefetch_transcription_model.sh

# Or prefetch as part of startup
./scripts/start_local_stack.sh --prefetch-transcription-model
```

Notes:
- First-time `medium` downloads are significantly larger/slower than `small`.
- Setting `HF_TOKEN` can improve HuggingFace Hub download reliability/speed.

### Choosing a pipeline preset (`pipeline_id`)

Pass `pipeline_id` to `POST /jobs` (form field). The orchestrator picks the matching manifest template:

```bash
# Default — smooth vertical reframe only (9 steps)
curl -F "source=@clip.mp4" http://127.0.0.1:8000/jobs

# Dead air + reframe (12 steps)
curl -F "source=@clip.mp4" -F "pipeline_id=reframe_16x9_to_9x16_dead_air" http://127.0.0.1:8000/jobs

# Audio quality chain + dead air + reframe (14 steps)
curl -F "source=@clip.mp4" -F "pipeline_id=reframe_16x9_to_9x16_audio_quality" http://127.0.0.1:8000/jobs
```

Background mode:

```bash
./scripts/start_local_stack.sh --detach
./scripts/stop_local_stack.sh
```

Then start the debug UI (separate terminal):

```bash
cd frontend && cp -n .env.local.example .env.local && npm install && npm run dev
```

Open **http://localhost:3000**, upload a 16:9 clip, run the pipeline, then preview/download when `final_9x16` appears.

To use segmented smooth rendering instead of a single static crop, set `compiler_render_mode` to `"smooth_crop"` under `service_config.render_plan_compiler` in [`contracts/examples/job_manifest.reframe_16x9_to_9x16.sample.json`](contracts/examples/job_manifest.reframe_16x9_to_9x16.sample.json) (orchestrator copies this template when creating jobs).

## Validation

Run the current focused test suite with:

```bash
.venv/bin/python -m unittest -v \
	services.validation.tests.test_validation_service \
	services.validation.tests.test_validation_api \
	services.media_metadata.tests.test_media_metadata_service \
	services.media_metadata.tests.test_media_metadata_api \
	services.audio_extraction.tests.test_audio_extraction_service \
	services.audio_extraction.tests.test_audio_extraction_api \
	services.audio_enhancement.tests.test_audio_enhancement_service \
	services.voice_activity_detection.tests.test_vad_service \
	services.voice_activity_detection.tests.test_vad_api \
	services.transcription.tests.test_transcription_service \
	services.dead_air_cut_planning.tests.test_dead_air_cut_planning_service \
	services.dead_air_cut_planning.tests.test_dead_air_cut_planning_api \
	services.proxy_frame_sampling.tests.test_proxy_frame_sampling_service \
	services.proxy_frame_sampling.tests.test_proxy_frame_sampling_api \
	services.body_detection.tests.test_body_detection_service \
	services.body_detection.tests.test_body_detection_api \
	services.track_interpolation.tests.test_track_interpolation_service \
	services.track_interpolation.tests.test_track_interpolation_api \
	services.reframe_planning.tests.test_reframe_planning_service \
	services.reframe_planning.tests.test_reframe_planning_api \
	services.easing_smoothing.tests.test_smoothing_service \
	services.easing_smoothing.tests.test_smoothing_api \
	services.render_plan_compiler.tests.test_compiler_service \
	services.render_plan_compiler.tests.test_compiler_api \
	services.ffmpeg_renderer.tests.test_ffmpeg_renderer_service \
	orchestrator.tests.test_path_resolver \
	orchestrator.tests.test_artifact_helpers \
	orchestrator.tests.test_pipeline_runner \
	orchestrator.tests.test_api \
	tests.integration.test_dead_air_fixtures \
	tests.integration.test_dead_air_render_plan_compiler_fixtures \
	tests.integration.test_dead_air_e2e \
	tests.integration.test_audio_quality_e2e
```

## What The Team Should Do Next

### Highest Priority

1. Wire `ORCHESTRATOR_SERVICE_ENDPOINTS` for `render_plan_compiler` and `ffmpeg_renderer` when running the full HTTP pipeline (implementations live under `services/render_plan_compiler/` and `services/ffmpeg_renderer/`).
2. Add P1-I01 and P1-I02 fixtures/integration coverage around the full pipeline (mock + real services).

### Orchestrator Team

- Keep all MinIO path construction inside `orchestrator/path_resolver.py`.
- Keep all manifest writes inside `ManifestManager`; do not update manifests inline inside controllers.
- Keep `HttpPipelineRunner` as the production path and retain `MockPipelineRunner` only as a local fallback.
- Preserve the existing step IDs from the contracts when wiring service execution.

### Service Teams

- Read the contracts first before writing any service output.
- Write only each service's own artifact or output object.
- Return deterministic output locations that match the Phase 1 contract.
- Do not invent new artifact keys without updating the shared contracts first.

### Frontend Team

- Use `GET /jobs/{job_id}/status` as the primary source for service state.
- Read artifact links from `artifact_manifest.json` rather than guessing object paths.
- Expect `run_job` to use real service calls only when `ORCHESTRATOR_SERVICE_ENDPOINTS` is configured; otherwise it falls back to the mock runner.

### QA And Integration

- Build fixtures and integration tests against the contract examples in `contracts/examples/`.
- Reuse the current Python tests as the baseline for helper and API behavior.
- Add pipeline-level tests around mock HTTP services first, then extend them to real services as they land.

## Known Limitations

- Real HTTP orchestration depends on `ORCHESTRATOR_SERVICE_ENDPOINTS`; without it, `run_job` still falls back to the mock runner.
- Debug Frontend under `frontend/` supports upload, status, run, and preview/download of `final_9x16.mp4` when that artifact exists (via orchestrator artifact GET).
- Body detection uses OpenCV HOG plus fallback logic — sufficient for Phase 1 baseline, not the final quality bar for hard clips.
- Smooth rendering uses segment concat between keyframes — acceptable MVP; per-frame expressions are not required yet.
- Production deployment (Docker/K8s, shared MinIO, CI) is not fully documented here.

## Recommended Immediate Task Order

1. P1-A04 through P1-H03 and P1-B03 (baseline done)
2. P1-I01 / P1-I02 / P1-I03 (fixtures, integration, e2e video)