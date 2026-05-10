# Phase 2 Todo - Dead Air Cutting

**Goal:** ต่อยอดจาก Phase 1 (16:9 → 9:16 smooth reframe) ให้รับวิดีโอเดิม 1 ไฟล์ แล้วตัดช่วงเงียบ (silence / dead air) ที่ยาวเกิน threshold ออกอัตโนมัติ ก่อน render เป็น 9:16  
**Scope:** เพิ่ม audio pipeline (extraction → VAD → cut plan) แล้วต่อเข้ากับ render pipeline เดิม โดย **ไม่ใช่** speaker diarization, ไม่ใช่ multi-cam, ไม่ใช่ split-screen, ไม่ใช่ reaction shot, ไม่ใช่ audio polish, ไม่ใช่ professional export, ไม่ใช่ auth/database

> Phase 1 (`Phase 1 Todo - 16x9 to 9x16 Smooth Reframe.md`) เป็น pre-requisite ทั้งหมด — Phase 2 *ขยาย* pipeline เดิม ไม่ทดแทน

## 1. Phase 2 Output ที่ต้องได้

ผู้ใช้สามารถ:

1. Upload วิดีโอ 16:9 จำนวน 1 ไฟล์ผ่าน Debug Frontend (เหมือน Phase 1)
2. เปิด/ปิด feature `remove_dead_air` ผ่าน toggle ใน Debug Frontend
3. เลือก threshold การตัด silence ได้ (เช่น `silence_threshold_seconds = 0.8`)
4. ให้ระบบ extract เสียงจากวิดีโอ และวิเคราะห์ช่วง speech/silence ด้วย VAD
5. สร้าง `cut_plan.json` ที่บอกว่าจะ keep ช่วงไหนของ source video บ้าง
6. Render output 9:16 ที่ตัด dead air แล้ว + reframe ตาม subject + จังหวะตัด jump cut เนียน
7. ดาวน์โหลดไฟล์ output ได้ และดู metric เช่น `total_silence_removed_seconds` ในหน้า status

## 2. Stack สำหรับ Phase 2

```text
Debug Frontend
  -> Orchestrator API
      -> MinIO
      -> Validation Service
      -> Media Metadata Service
      -> Audio Extraction Service             (new)
      -> Voice Activity Detection Service     (new)
      -> Dead Air Cut Planning Service        (new — F-01 ใน Modular Service Breakdown)
      -> Proxy/Frame Sampling Service
      -> Body Detection Service
      -> Track Interpolation Service
      -> Reframe Planning Service
      -> Easing/Smoothing Service
      -> Render Plan Compiler Service         (extended)
      -> FFmpeg Renderer Service              (extended)
```

หลักคิด:

- Audio pipeline (Extraction → VAD → Cut Planning) **ทำก่อน** vision pipeline เพื่อ fail fast ถ้าไม่มีเสียงพูด
- Cut Planning Service ส่ง `cut_plan.json` (keep segments บน timeline ของ **source video**)
- Render Plan Compiler รวม `cut_plan.json` + `reframe_plan_smooth.json` ให้เป็นแผนเดียว — ไม่ render หลายรอบ
- FFmpeg Renderer ทำ trim → crop ต่อ segment → concat → mux audio ใน pass เดียว เพื่อให้ output มีจังหวะตัดที่ frame-accurate

## 3. MinIO Layout สำหรับ Phase 2

โครง Phase 1 เดิมคงเดิมทุกอย่าง เพิ่ม artifact ใหม่ 3 ตัว:

```text
jobs/{job_id}/
  input/
    source.mp4
  manifests/
    job_manifest.json
    artifact_manifest.json
    service_status.json
  artifacts/
    metadata.json
    extracted_audio.wav                       (new)
    vad_segments.json                         (new)
    cut_plan.json                             (new)
    proxy.mp4
    sampled_frames.json
    body_tracks_raw.json
    body_tracks_interpolated.json
    reframe_plan_raw.json
    reframe_plan_smooth.json
    render_plan.json
  outputs/
    final_9x16.mp4
  logs/
    orchestrator.log
    audio_extraction.log                      (new)
    voice_activity_detection.log              (new)
    dead_air_cut_planning.log                 (new)
    body_detection.log
    reframe_planning.log
    easing_smoothing.log
    renderer.log
```

## 4. Service Todo

### S-12: Audio Extraction Service

**Purpose:** แยก audio track ออกจาก source video เป็น mono WAV สำหรับ VAD

Todo:

- รับ `job_manifest.input.source_video.object_key`
- ใช้ `ffmpeg -vn -ac 1 -ar 16000 -c:a pcm_s16le` แยก audio
- เขียน `artifacts/extracted_audio.wav` (16 kHz, mono, PCM 16-bit ตามมาตรฐาน Silero VAD)
- ถ้า source ไม่มี audio stream ให้ fail พร้อม error อ่านรู้เรื่อง — เพราะ Phase 2 ทั้งหมดต้องอาศัยเสียง
- เขียน log ระยะเวลาที่ใช้และ sample rate/duration ที่ได้

Output example (`extracted_audio.wav` metadata embed ลง `service_status.json` warnings ถ้าจำเป็น):

```json
{
  "object_key": "jobs/job_001/artifacts/extracted_audio.wav",
  "sample_rate": 16000,
  "channels": 1,
  "duration_seconds": 120.4
}
```

**Failure policy:** `fail_job`

Done when:

- WAV mono 16 kHz เปิดด้วย `wave` ของ Python หรือ `soxi` ได้
- duration ใกล้เคียง source video (ไม่เกิน ±0.1s)

---

### S-13: Voice Activity Detection Service

**Purpose:** แบ่งเสียงเป็นช่วง `speech` / `silence` ตาม timestamp ของ source video

Todo:

- โหลด `extracted_audio.wav`
- รัน Silero VAD (PyTorch CPU ก็พอใน MVP, GPU เป็น nice-to-have)
- คืนผลเป็น array ของ `{ start, end, type, confidence }` โดย type ∈ `speech | silence`
- merge ช่วง speech ที่อยู่ติดกันถ้าห่างกันน้อยมาก (เช่น <0.1s)
- ใส่ confidence score ของ VAD ทุกช่วง
- เขียน `artifacts/vad_segments.json`

Config (อยู่ใน `job_manifest.service_config.voice_activity_detection`):

```json
{
  "model": "silero_v4",
  "speech_threshold": 0.5,
  "min_speech_duration_seconds": 0.25,
  "min_silence_duration_seconds": 0.2
}
```

Output example:

```json
{
  "schema_version": "2.0.0",
  "model": "silero_v4",
  "segments": [
    { "start": 0.0,  "end": 1.85, "type": "silence", "confidence": 0.97 },
    { "start": 1.85, "end": 12.4, "type": "speech",  "confidence": 0.92 },
    { "start": 12.4, "end": 14.6, "type": "silence", "confidence": 0.95 }
  ]
}
```

**Failure policy:** `fail_job` (เพราะถ้า VAD พังก็ตัด dead air ไม่ได้)

Done when:

- segments ครอบคลุมทั้ง duration ของ video โดยไม่มี gap ที่ไม่ classified
- ผลลัพธ์ deterministic เมื่อ input เดียวกัน

---

### S-14: Dead Air Cut Planning Service (F-01)

**Purpose:** แปลง `vad_segments.json` ให้กลายเป็น `cut_plan.json` ที่บอกว่าจะ **keep** ช่วงไหนของ source video

Todo:

- อ่าน `vad_segments.json` และ `metadata.json`
- ถ้า `enabled_features.remove_dead_air = false` → emit identity cut plan (keep ทั้ง video เป็น 1 segment)
- ถ้า `true`:
  - ลบ silence segment ที่ยาว `> silence_threshold_seconds`
  - silence ที่สั้นกว่า threshold → รวมเข้ากับ speech ข้าง ๆ (ไม่ตัด)
  - เก็บ padding รอบ speech: `keep_padding_before` ก่อน start, `keep_padding_after` หลัง end เพื่อไม่ให้พยางค์ขาดหาย
  - merge keep segment ที่ติดกันหรือซ้อนกันหลังเพิ่ม padding
- คำนวณ metric: `total_kept_seconds`, `total_removed_seconds`, `cut_count`, `compression_ratio`
- เขียน `artifacts/cut_plan.json`

Config (อยู่ใน `job_manifest.service_config.dead_air_cut_planning`):

```json
{
  "silence_threshold_seconds": 0.8,
  "keep_padding_before": 0.15,
  "keep_padding_after": 0.20,
  "min_keep_segment_seconds": 0.5
}
```

Output example:

```json
{
  "schema_version": "2.0.0",
  "source_duration_seconds": 120.4,
  "feature_enabled": true,
  "config_used": {
    "silence_threshold_seconds": 0.8,
    "keep_padding_before": 0.15,
    "keep_padding_after": 0.20
  },
  "keep_segments": [
    { "source_start": 1.70, "source_end": 14.55 },
    { "source_start": 17.20, "source_end": 36.80 }
  ],
  "metrics": {
    "total_kept_seconds": 32.45,
    "total_removed_seconds": 87.95,
    "cut_count": 1,
    "compression_ratio": 0.27
  }
}
```

กฎสำคัญ:

- `keep_segments` ต้องเรียงตาม `source_start` และห้ามซ้อนกัน
- coordinate ใช้ source-video timeline ทั้งหมด — ไม่ใช่ output timeline
- ห้ามตัด segment เดียวให้สั้นกว่า `min_keep_segment_seconds` (รวมกับ segment ข้างเคียงแทน)

**Failure policy:** `fallback_to_default` — ถ้า fail ให้ emit identity cut plan + warning เพื่อไม่ block render

Done when:

- รวม `total_kept_seconds + total_removed_seconds ≈ source_duration_seconds`
- เปิด feature ปิดแล้ว job ยังเดินจนจบเหมือน Phase 1 ทุกประการ

---

### S-15 (Extended): Render Plan Compiler Service

**Purpose:** รวม `reframe_plan_smooth.json` + `cut_plan.json` เป็นแผน render เดียว

Todo (ส่วนเพิ่มจาก Phase 1):

- โหลด `cut_plan.json` (ถ้ามี)
- สำหรับแต่ละ `keep_segments[i]`:
  - ดึง crop keyframes ของ `reframe_plan_smooth.json` ที่ `source_start ≤ t ≤ source_end`
  - ถ้า `source_start` ไม่ตรงกับ keyframe เดิม ให้ interpolate crop position ที่ขอบ segment
  - คำนวณ `output_start`, `output_end` (timeline หลังตัด) ต่อ segment
- emit `render_plan.json` mode ใหม่ `smooth_crop_with_cuts`
- ถ้า cut plan เป็น identity → fallback ไป mode `smooth_crop` เดิมของ Phase 1 ตรง ๆ (ไม่เปลี่ยนพฤติกรรม)

Schema เพิ่มใน `job_manifest.service_config.render_plan_compiler.compiler_render_mode`:

```text
static_crop | smooth_crop | smooth_crop_with_cuts
```

Output example (สำหรับ `smooth_crop_with_cuts`):

```json
{
  "input": "jobs/job_001/input/source.mp4",
  "output": "jobs/job_001/outputs/final_9x16.mp4",
  "target_resolution": { "width": 1080, "height": 1920 },
  "render_mode": "smooth_crop_with_cuts",
  "audio_codec": "aac",
  "video_codec": "libx264",
  "segments": [
    {
      "segment_id": "seg_000",
      "source_start": 1.70,
      "source_end": 14.55,
      "output_start": 0.0,
      "output_end": 12.85,
      "crop_keyframes": [
        { "t_source": 1.70,  "x": 650, "y": 0 },
        { "t_source": 14.55, "x": 712, "y": 0 }
      ]
    }
  ]
}
```

Done when:

- จำนวน segment เท่ากับ `keep_segments` ใน cut plan
- `sum(output_end - output_start) == cut_plan.metrics.total_kept_seconds` (ภายใน tolerance 0.05s)
- crop ขอบ segment ไม่หลุดจาก source video

---

### S-16 (Extended): FFmpeg Renderer Service

**Purpose:** render ในรอบเดียวให้ได้ output 9:16 ที่ตัด dead air + smooth crop

Todo (ส่วนเพิ่มจาก Phase 1):

- รองรับ `render_mode = smooth_crop_with_cuts`
- ต่อ segment:
  1. Trim source ตาม `source_start`/`source_end` (re-encode บังคับ ไม่ใช้ stream copy เพราะอาจไม่ตรง keyframe)
  2. Apply crop ตาม `crop_keyframes` ของ segment นั้น (segment-based concat ตาม Phase 1 H03)
  3. Scale เป็น `1080x1920`
- Concat ทุก segment เป็น video stream เดียว
- Trim audio ตาม source ranges เดียวกัน → concat → mux ใส่ video
- Validate ความยาว output ≈ `cut_plan.metrics.total_kept_seconds`
- Upload `outputs/final_9x16.mp4`

กฎสำคัญ:

- การตัด audio ต้องใช้ source ranges เดียวกับ video เป๊ะ ๆ ห้าม drift
- ห้ามให้ silence segment ที่ตัดออกหลุดเข้ามา (กัน A/V desync ด้วยการ re-encode ทั้ง audio และ video ให้ frame/sample boundary ตรงกัน)
- ถ้า cut count = 0 หรือ feature ปิด → behavior เหมือน Phase 1 H03 ทุกประการ

Done when:

- output เล่นได้, ภาพ+เสียงตัดติดกันแบบ jump cut ไม่ดีเลย์
- ความยาวใกล้เคียง `total_kept_seconds` (±0.1s)
- ไม่มี silence ยาว ๆ หลุดมาใน output

---

### S-17 (Extended): Debug Frontend

**Purpose:** debug UI ของ Phase 2 — toggle feature, แสดง cut plan, preview before/after

Todo:

- เพิ่ม checkbox `Remove dead air` ในหน้า upload
- เพิ่ม slider/input สำหรับ `silence_threshold_seconds` (default 0.8s)
- หน้า `/jobs/[jobId]` เพิ่ม:
  - แสดง 12 step (เพิ่ม `audio_extraction`, `voice_activity_detection`, `dead_air_cut_planning`)
  - แสดง metric จาก `cut_plan.json`: `total_removed_seconds`, `cut_count`, `compression_ratio`
  - artifact links ใหม่: `extracted_audio.wav` (download), `vad_segments.json`, `cut_plan.json`
  - timeline visualizer แบบง่าย: แท่งสีเทาคือ silence ที่ตัดออก, แท่งสีเขียวคือ keep segment (ดึงจาก `cut_plan.json`)
- ปุ่ม download `final_9x16.mp4` คงเดิม

Done when:

- Toggle feature off → 9 step + behavior Phase 1 เดิม
- Toggle feature on → 12 step + แสดง cut plan + preview output ที่ตัดแล้ว
- Timeline visualizer match กับ keep_segments ใน cut plan

## 5. Parallel Todo Board

รายการนี้เป็น Markdown task list สำหรับติ๊กสถานะ — เปลี่ยน `[ ]` เป็น `[x]` เมื่อเสร็จ ลำดับ ID ต่อจาก Phase 1 ตาม lane เดิม + lane ใหม่ J/K/L

- [x] P2-A01: Bump contracts สำหรับ Phase 2 — เพิ่ม preset dead-air `pipeline_id = "reframe_16x9_to_9x16_dead_air"`, ขยาย `pipeline.steps` array, เพิ่ม `enabled_features.remove_dead_air` ใน `job_manifest.schema.json`, schema_version `2.0.0`
  Owner: Orchestrator | Write Scope: `contracts/` เท่านั้น | Depends on: P1-A01 | Deliverable: schema + sample manifest ใหม่ใน `contracts/examples/`
- [x] P2-A02: ขยาย `artifact_manifest.schema.json` — เพิ่ม artifact key `extracted_audio`, `vad_segments`, `cut_plan` พร้อม pattern + producer
  Owner: Orchestrator | Write Scope: `contracts/` เท่านั้น | Depends on: P2-A01 | Deliverable: schema ใหม่ + sample artifact manifest
- [x] P2-A03: ขยาย `path_resolver.py` และ `artifact_helper.py` ให้รู้จัก artifact key ใหม่ 3 ตัว
  Owner: Orchestrator | Write Scope: `orchestrator/` เท่านั้น | Depends on: P2-A02 | Deliverable: helper อ่าน/เขียน 3 artifact ใหม่ + tests
- [x] P2-A04: ขยาย `HttpPipelineRunner` + `MockPipelineRunner` ให้รู้ pipeline 12 step ใหม่ และ route service URL ใหม่ 3 ตัว
  Owner: Orchestrator | Write Scope: `orchestrator/` เท่านั้น | Depends on: P2-A01, P2-A02 | Deliverable: runner รัน 12 step ตามลำดับ + integration test
- [x] P2-A05: ขยาย `ORCHESTRATOR_SERVICE_ENDPOINTS` env + `scripts/start_local_stack.sh` ให้ start service ใหม่ 3 ตัวบน `127.0.0.1:8019–8021`
  Owner: Orchestrator | Write Scope: `scripts/`, README, env config | Depends on: P2-J02, P2-K02, P2-L02 | Deliverable: รัน `./scripts/start_local_stack.sh` แล้วได้ 12 service บน localhost
- [x] P2-J01: ทำ Audio Extraction Service skeleton (`/run` endpoint)
  Owner: Audio | Write Scope: `services/audio_extraction/` เท่านั้น | Depends on: P2-A02 | Deliverable: FastAPI `/run` ที่อ่าน source key จาก manifest, mock ก่อน
- [x] P2-J02: ทำ ffmpeg audio extraction จริงเขียน WAV mono 16 kHz
  Owner: Audio | Write Scope: `services/audio_extraction/` เท่านั้น | Depends on: P2-J01 | Deliverable: `extracted_audio.wav` ใช้ได้ + tests
- [x] P2-K01: ทำ Voice Activity Detection Service skeleton + เลือก backend (Silero VAD)
  Owner: Audio AI | Write Scope: `services/voice_activity_detection/` เท่านั้น | Depends on: P2-A02, P2-J02 | Deliverable: skeleton + Silero pinned ใน `requirements.txt`
- [x] P2-K02: ทำ VAD จริง emit `vad_segments.json` ครอบคลุมทั้ง duration
  Owner: Audio AI | Write Scope: `services/voice_activity_detection/` เท่านั้น | Depends on: P2-K01 | Deliverable: artifact + tests + log
- [x] P2-K03: tuning threshold + handle edge case (วิดีโอเงียบทั้งคลิป, วิดีโอพูดทั้งคลิป)
  Owner: Audio AI | Write Scope: `services/voice_activity_detection/` เท่านั้น | Depends on: P2-K02 | Deliverable: warning policy + test fixtures 3 แบบ
- [x] P2-L01: ทำ Dead Air Cut Planning Service skeleton
  Owner: Timeline/Feature | Write Scope: `services/dead_air_cut_planning/` เท่านั้น | Depends on: P2-A02 | Deliverable: FastAPI `/run` skeleton
- [x] P2-L02: implement cut planning algorithm — threshold + padding + merge + min keep duration
  Owner: Timeline/Feature | Write Scope: `services/dead_air_cut_planning/` เท่านั้น | Depends on: P2-K02, P2-L01 | Deliverable: `cut_plan.json` + tests ครอบคลุม edge case (silence ทั้งคลิป, ไม่มี silence, padding ทับกัน, segment สั้นเกิน)
- [x] P2-L03: identity mode + metrics ครบ (`total_removed_seconds`, `cut_count`, `compression_ratio`)
  Owner: Timeline/Feature | Write Scope: `services/dead_air_cut_planning/` เท่านั้น | Depends on: P2-L02 | Deliverable: feature off → identity plan, feature on → metrics ตรงกับการ verify ด้วย ffprobe
- [x] P2-H04: ขยาย Render Plan Compiler รองรับ `compiler_render_mode = smooth_crop_with_cuts`
  Owner: Renderer | Write Scope: `services/render_plan_compiler/` เท่านั้น | Depends on: P2-L02, P1-H01 | Deliverable: render_plan ใหม่ที่มี `segments[]` + interpolate crop ที่ขอบ
- [x] P2-H05: ขยาย FFmpeg Renderer ทำ trim + crop ต่อ segment + concat + mux เสียงในรอบเดียว
  Owner: Renderer | Write Scope: `services/ffmpeg_renderer/` เท่านั้น | Depends on: P2-H04, P1-H03 | Deliverable: output `final_9x16.mp4` ที่ตัด dead air + reframed
- [x] P2-H06: ตรวจ A/V sync ของ output — สร้าง smoke test ว่า audio sample boundary ตรงกับ video frame boundary หลัง concat
  Owner: Renderer | Write Scope: `services/ffmpeg_renderer/tests/` เท่านั้น | Depends on: P2-H05 | Deliverable: test ที่ fail ถ้ามี desync > 1 frame
- [x] P2-B04: เพิ่ม toggle `Remove dead air` + `silence_threshold_seconds` ในหน้า upload
  Owner: Frontend | Write Scope: `frontend/` เท่านั้น | Depends on: P2-A01 | Deliverable: UI ส่ง `enabled_features.remove_dead_air` + config เข้า create job
- [x] P2-B05: รองรับ pipeline 12 step ในหน้า status — แสดง 3 step ใหม่ + artifacts ใหม่ 3 ตัว
  Owner: Frontend | Write Scope: `frontend/` เท่านั้น | Depends on: P2-A02, P2-B04 | Deliverable: หน้า status ดู step ใหม่ได้, ดาวน์โหลด `extracted_audio.wav`, ดู `vad_segments.json` / `cut_plan.json`
- [x] P2-B06: timeline visualizer แสดง keep/removed segment จาก `cut_plan.json` + metric (kept/removed/ratio)
  Owner: Frontend | Write Scope: `frontend/` เท่านั้น | Depends on: P2-L02, P2-B05 | Deliverable: bar chart หรือ track view เรียงตาม source timeline
- [x] P2-I04: sample fixture ของ Phase 2 — vad_segments + cut_plan + render_plan ตัวอย่าง 3 แบบ (ตัดเยอะ, ตัดน้อย, ไม่ตัด)
  Owner: QA/Integration | Write Scope: `fixtures/` เท่านั้น | Depends on: P2-A02 | Deliverable: ไฟล์ fixture ที่ผ่าน schema validation
- [x] P2-I05: integration test ของ pipeline 12 step ด้วย mock services
  Owner: QA/Integration | Write Scope: integration test เท่านั้น | Depends on: P2-A04, P2-I04 | Deliverable: pipeline วิ่งครบ + assert artifact crud
- [x] P2-I06: end-to-end test ด้วยวิดีโอจริงสั้น ๆ (มี silence ที่ตั้งใจ) → assert duration output ตรงกับ `total_kept_seconds`
  Owner: QA/Integration | Write Scope: integration test เท่านั้น | Depends on: P2-H05, P2-I04 | Deliverable: e2e ผ่าน acceptance criteria

### Dependency กลางของ Phase 2

- P2-A01 ต้องเสร็จก่อนทุก service เพราะ schema ใหม่เป็น contract
- P2-A02 ต้องเสร็จก่อน P2-A03, P2-A04, ทุก service ใหม่ (J/K/L)
- P2-J02 ต้องเสร็จก่อน P2-K02 เพราะ VAD ใช้ WAV เป็น input
- P2-K02 ต้องเสร็จก่อน P2-L02 เพราะ cut planning ใช้ vad_segments
- P2-L02 ต้องเสร็จก่อน P2-H04 เพราะ render compiler รวม cut plan
- P2-H04 ต้องเสร็จก่อน P2-H05 (renderer อ่าน render_plan)
- P2-H05 ต้องเสร็จก่อน P2-I06
- P2-A04 ต้องเสร็จก่อน P2-I05 (integration test ใช้ runner ใหม่)

### งานที่เริ่มได้ทันที (เมื่อกด start Phase 2)

- Orchestrator: P2-A01 (contract bump) — unblock ทุกคน
- Audio team: P2-J01 skeleton (ใช้ mock manifest จาก fixture ได้ก่อน contract bump เสร็จ)
- Renderer: ออกแบบ schema ของ `cut_plan.json` ร่วมกับ Timeline team (paper design ก่อน)
- Frontend: P2-B04 wireframe + types ใหม่
- QA: P2-I04 sample fixture (ใช้ schema draft ของ P2-A01 ได้)

### Parallelism ภายใน Phase 2

- Audio chain (J → K → L) **ขนาน** กับ Phase 1 vision chain ได้ในแง่ implementation — แต่ runtime ยังเรียง sequential ผ่าน Orchestrator (เพื่อความเรียบ)
- Frontend (B04–B06) ขนานกับทุก service ได้ตั้งแต่ contract draft พร้อม (ใช้ types ตาม schema ใหม่)
- Renderer extension (H04–H06) **ต้องรอ** L02 เสร็จก่อน

## 6. Phase 2 Pipeline (เต็ม)

```text
Create Job
  -> Upload source.mp4
  -> Validation Service
  -> Media Metadata Service
  -> Audio Extraction Service
  -> Voice Activity Detection Service
  -> Dead Air Cut Planning Service
  -> Proxy/Frame Sampling Service
  -> Body Detection Service
  -> Track Interpolation Service
  -> Reframe Planning Service
  -> Easing/Smoothing Service
  -> Render Plan Compiler Service        (consumes cut_plan + reframe_plan)
  -> FFmpeg Renderer Service             (trim + crop + concat + mux ในรอบเดียว)
  -> Download final_9x16.mp4
```

### Preset IDs และความเข้ากันได้กับ reframe-only

- Jobs แบบ reframe-only ใช้ `pipeline_id = "reframe_16x9_to_9x16"` (9 steps)
- Jobs dead-air ใช้ `pipeline_id = "reframe_16x9_to_9x16_dead_air"` (12 steps)
- Orchestrator เลือกลำดับ step ตาม `pipeline_id` ใน job manifest
- ถ้า dead-air job set `enabled_features.remove_dead_air = false` → audio chain ยัง run แต่ cut planning emit identity plan, renderer fallback ไป mode `smooth_crop` เดิม (ผลลัพธ์เทียบเท่า preset reframe-only)

## 7. Phase 2 Feature ที่ยังไม่ทำ (กันไว้ Phase 3)

- multi-camera input
- audio sync (ของ multi-cam)
- speaker diarization
- speaker-to-camera mapping
- dynamic split-screen
- reaction shot
- auto-audio polish (LUFS / noise gate / ducking)
- professional export (FCPXML / EDL)
- timeline editor เต็มรูปแบบ
- manual override ของ cut plan ผ่าน frontend
- auth / database / multi-tenant

## 8. Risk / จุดที่ต้องระวัง

- **A/V drift หลัง concat:** trim+concat บน video และ audio ต้องใช้ source ranges เดียวกัน เป๊ะ — ห้าม audio drift จาก video แม้แต่ frame เดียว
- **Frame-accurate trim:** `-ss` ก่อน `-i` กับหลัง `-i` ต่างกัน — Phase 2 ใช้หลัง `-i` + re-encode บังคับเสมอ
- **Padding ทับกัน:** keep_padding_before/after รวมกันแล้ว keep segments อาจ overlap → cut planning ต้อง merge หลังเพิ่ม padding
- **คลิปที่เงียบทั้งหมด:** VAD จะคืน silence ทั้งหมด → cut planning ต้อง fail soft + warning ไม่ render เป็น 0 byte
- **คลิปที่พูดทั้งหมด:** cut count = 0 → ต้อง fallback ไป Phase 1 behavior อัตโนมัติ
- **คลิปสั้นมาก (<2s):** padding อาจกินเกินตัวคลิป → clamp กับ `[0, source_duration]`
- **Re-encode ซ้ำซ้อน:** trim + concat ทำให้ encode 2 ครั้ง — ใน MVP ยอมรับได้, future อาจรวมเป็น 1 ffmpeg invocation ด้วย `filter_complex` เดียว
- **Subject กลางช่วง silence:** ถ้า silence ที่ตัดออกพอดีอยู่ตรงที่ subject กำลังเดินข้ามจอ → crop หลังตัดอาจกระโดด — solution: smoothing ทำงานบน source timeline เดิม, segment boundary แค่ snap ไป crop ที่ interpolate มา
- **VAD model size:** Silero ~2 MB ใส่ใน Docker ได้, แต่ถ้าโตขึ้นต้อง mount แยก
- **GPU vs CPU:** Phase 2 ทำ CPU-only ได้ทั้งหมด (Silero CPU เร็วพอ); GPU ไว้ Phase 3 (เมื่อมี diarization)

## 9. Acceptance Criteria

Phase 2 ถือว่าผ่านเมื่อ:

- ใช้วิดีโอ 16:9 หนึ่งไฟล์ (มีเสียงพูด + มี silence ที่ชัดเจน) เป็น input ได้
- toggle `remove_dead_air = true` แล้วได้ output 9:16 ที่:
  - ความยาวสั้นกว่า input ตามจำนวน silence ที่ตัด
  - silence ยาว ๆ ที่ตั้งใจไม่หลุดเข้ามาใน output
  - ภาพและเสียงตัดติดกันแบบ jump cut โดยไม่ desync
  - subject ยังอยู่ในกรอบเหมือน Phase 1
- toggle `remove_dead_air = false` แล้วได้ output **เหมือน Phase 1 ทุกประการ** (ไม่ regression)
- ทุก service เขียน artifact ของตัวเองลง MinIO (`extracted_audio.wav`, `vad_segments.json`, `cut_plan.json` ครบ)
- `service_status.json` แสดง 12 step ครบและ status ไหลครบ
- Orchestrator รัน pipeline ได้โดยไม่ต้องใช้ frontend
- Debug Frontend ใช้ดู status, cut plan, ดาวน์โหลด output, ดู metric ได้
- คลิปที่เงียบทั้งหมดไม่ทำให้ pipeline crash — emit warning + fallback อย่างเหมาะสม
- คลิปที่พูดทั้งหมด → cut_count = 0, output เท่ากับ Phase 1
