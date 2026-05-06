# Automated Podcast Editor - Service Breakdown

**Document Version:** 2.0  
**Purpose:** ออกแบบระบบเป็น service แยกส่วนจริง แต่ยังคงง่ายพอสำหรับ MVP โดยใช้ Frontend เป็น Debug UI, ใช้ MinIO เป็นที่เก็บไฟล์/manifest/artifact และไม่บังคับใช้ Database

## 1. เป้าหมายการออกแบบ

ระบบต้องแบ่งเป็น service ที่พัฒนา แทนที่ หรือถอดออกได้ โดยไม่ทำให้ส่วนอื่นพัง แต่ยังไม่ต้องทำ infrastructure ซับซ้อน

หลักคิด:

- แต่ละ service รับ input เป็นไฟล์หรือ JSON artifact
- แต่ละ service เขียน output กลับเป็นไฟล์หรือ JSON artifact
- ไม่มี service ไหนเรียก internal code ของ service อื่นโดยตรง
- การเชื่อมกันใช้ contract กลางผ่าน `job_manifest.json`, `artifact_manifest.json`, `timeline.json`
- Frontend มีไว้ debug, upload, trigger, ดู status, preview result ไม่ใช่ product UI จริง
- ไม่ต้องมี auth, database, billing, multi-tenant, admin panel ใน MVP

## 2. MVP Runtime Stack

```text
Debug Frontend
  -> Orchestrator API
      -> MinIO
      -> Service Workers
          -> Media Services
          -> Audio AI Services
          -> Vision AI Services
          -> Timeline Feature Services
          -> Renderer Service
```

### Component หลัก

- **Debug Frontend:** หน้าเว็บสำหรับ upload, เลือก config, trigger job, ดู artifact, แก้ timeline แบบง่าย
- **Orchestrator API:** service กลางสำหรับสร้าง job, เรียก service ตาม pipeline, อ่าน/เขียน manifest
- **MinIO:** source of truth สำหรับไฟล์ทั้งหมด รวมถึง state ของ job
- **Service Workers:** service เฉพาะทางที่รับ job id แล้วอ่าน input จาก MinIO และเขียน output กลับ MinIO

### สิ่งที่ยังไม่ต้องมี

- Database
- Auth/Login
- User management
- Kubernetes
- Message broker แบบ production
- Separate queue ต่อ service
- Observability stack เต็มรูปแบบ
- Frontend ที่สวยแบบ production

## 3. MinIO เป็น Source of Truth

เพราะ MVP ไม่ใช้ database ให้ทุกอย่างอยู่ใน MinIO ภายใต้ job เดียวกัน

### Bucket แนะนำ

```text
smart-cut
```

### Object Layout แนะนำ

```text
jobs/{job_id}/
  input/
    cam_host.mp4
    cam_guest.mp4
    master.wav
  manifests/
    job_manifest.json
    artifact_manifest.json
    service_status.json
  artifacts/
    metadata.json
    extracted_audio/
      cam_host.wav
      cam_guest.wav
    sync_offsets.json
    vad_segments.json
    diarization.json
    speaker_map.json
    body_tracks.json
    face_tracks.json
    timeline_raw.json
    timeline_transformed.json
    timeline_reviewed.json
    render_plan.json
  outputs/
    final.mp4
    export.fcpxml
    export.edl
  logs/
    orchestrator.log
    media_metadata.log
    renderer.log
```

### State แบบไม่ใช้ Database

`service_status.json` ใช้เก็บสถานะล่าสุดของแต่ละ service

```json
{
  "job_id": "job_001",
  "status": "running",
  "current_step": "speaker_diarization",
  "steps": {
    "validation": {
      "status": "success",
      "started_at": "2026-05-06T10:00:00Z",
      "finished_at": "2026-05-06T10:00:02Z"
    },
    "speaker_diarization": {
      "status": "running",
      "started_at": "2026-05-06T10:05:00Z"
    }
  },
  "warnings": [],
  "errors": []
}
```

ข้อควรระวัง: ถ้ามี worker หลายตัวเขียนไฟล์เดียวกันพร้อมกันจะเกิด race ได้ ดังนั้น MVP ให้ Orchestrator เป็นคนควบคุมลำดับ และให้ service แต่ละตัวเขียน output path ของตัวเองเท่านั้น

## 4. Service Communication

MVP ใช้ HTTP ระหว่าง Orchestrator กับ service ได้ง่ายที่สุด

### Service API กลาง

ทุก service ควรมี endpoint รูปแบบเดียวกัน

```text
POST /run
```

Request:

```json
{
  "job_id": "job_001",
  "minio": {
    "bucket": "smart-cut",
    "prefix": "jobs/job_001"
  },
  "inputs": {
    "job_manifest": "jobs/job_001/manifests/job_manifest.json",
    "artifact_manifest": "jobs/job_001/manifests/artifact_manifest.json"
  },
  "config": {}
}
```

Response:

```json
{
  "service_id": "reaction_shot",
  "status": "success",
  "outputs": {
    "timeline": "jobs/job_001/artifacts/timeline_transformed.json"
  },
  "warnings": []
}
```

### Failure Policy

แต่ละ service ต้องประกาศ failure policy:

- `fail_job`: fail แล้วหยุดทั้ง job เช่น validation, renderer
- `skip_and_warn`: fail แล้วข้ามได้ เช่น reaction shot, split-screen
- `fallback_to_default`: fail แล้วใช้ output เดิม เช่น auto-reframe ใช้ crop center

## 5. Shared Contracts

### 5.1 Job Manifest

`job_manifest.json` คือ config หลักของงาน

```json
{
  "job_id": "job_001",
  "input_videos": [
    {
      "asset_id": "cam_host",
      "object_key": "jobs/job_001/input/cam_host.mp4",
      "role": "Host",
      "is_master_audio": true,
      "mute_in_render": false
    },
    {
      "asset_id": "cam_guest",
      "object_key": "jobs/job_001/input/cam_guest.mp4",
      "role": "Guest",
      "is_master_audio": false,
      "mute_in_render": true
    }
  ],
  "target_output": {
    "aspect_ratio": "16:9",
    "resolution": "1920x1080",
    "format": "mp4"
  },
  "enabled_features": {
    "remove_dead_air": true,
    "auto_reframe": false,
    "split_screen": true,
    "reaction_shot": true,
    "audio_polish": false,
    "professional_export": false
  }
}
```

### 5.2 Artifact Manifest

`artifact_manifest.json` คือ registry ของ output ที่แต่ละ service สร้าง

```json
{
  "job_id": "job_001",
  "artifacts": {
    "metadata": "jobs/job_001/artifacts/metadata.json",
    "vad_segments": "jobs/job_001/artifacts/vad_segments.json",
    "diarization": "jobs/job_001/artifacts/diarization.json",
    "timeline_raw": "jobs/job_001/artifacts/timeline_raw.json",
    "timeline_transformed": "jobs/job_001/artifacts/timeline_transformed.json",
    "render_plan": "jobs/job_001/artifacts/render_plan.json",
    "final_video": "jobs/job_001/outputs/final.mp4"
  }
}
```

### 5.3 Timeline Segment

```json
{
  "segment_id": "seg_001",
  "start": 10.25,
  "end": 16.8,
  "type": "speech",
  "speaker_id": "speaker_1",
  "source_asset_id": "cam_host",
  "layout": "single",
  "confidence": 0.92,
  "effects": [],
  "metadata": {
    "manual_override": false,
    "generated_by": ["speaker_diarization", "base_timeline"]
  }
}
```

## 6. Core Services

### S-01: Orchestrator API

**หน้าที่:** เป็น service กลางที่ frontend ใช้คุย และเป็นตัวเรียก service อื่นตาม pipeline

**Input:** upload request, job config  
**Output:** job id, service status, artifact links

**ต้องทำ**

- สร้าง `job_id`
- upload หรือรับ object key จาก frontend
- เขียน `job_manifest.json`
- เขียน/อัปเดต `service_status.json`
- เรียก service ตามลำดับผ่าน HTTP
- update `artifact_manifest.json`
- return URL สำหรับ debug/download

**ไม่ต้องทำ**

- ไม่ต้อง render เอง
- ไม่ต้องรัน AI เอง
- ไม่ต้องเก็บ state ใน database
- ไม่ต้องมี auth ใน MVP

### S-02: Validation Service

**หน้าที่:** ตรวจ job config ก่อนเริ่ม pipeline

**Input:** `job_manifest.json`  
**Output:** validation result ใน `service_status.json`

**ตรวจอย่างน้อย**

- จำนวนกล้อง 1-5
- มี master audio เพียงตัวเดียว
- ถ้า multi-cam ต้องมี `Wide` หรือ fallback camera
- aspect ratio conflict
- feature ที่เปิดต้องมี input เพียงพอ

**Failure policy:** `fail_job`

### S-03: Artifact Registry Service

**หน้าที่:** helper service หรือ module ของ Orchestrator สำหรับอ่าน/เขียน `artifact_manifest.json`

**Input:** service output response  
**Output:** updated `artifact_manifest.json`

**หมายเหตุ:** ใน MVP อาจไม่ต้องแยก process เป็น service จริง แต่ออกแบบ contract ให้ชัดเพื่อเปลี่ยนภายหลังได้

## 7. Media Services

### S-04: Media Metadata Service

**หน้าที่:** อ่าน metadata ของไฟล์ด้วย `ffprobe`

**Input:** input video/audio object keys  
**Output:** `artifacts/metadata.json`

**Failure policy:** `fail_job`

### S-05: Audio Extraction Service

**หน้าที่:** แยกเสียงจากวิดีโอทุกไฟล์เพื่อใช้ sync และ AI

**Input:** input videos  
**Output:** `artifacts/extracted_audio/{asset_id}.wav`

**Failure policy:** `fail_job`

### S-06: Media Normalization Service

**หน้าที่:** แปลง FPS/resolution ให้ตรงกันเมื่อจำเป็น

**Input:** input videos, `metadata.json`  
**Output:** normalized videos หรือ no-op result

**Failure policy:** `fallback_to_default` ถ้าไฟล์เข้ากันได้อยู่แล้ว, `fail_job` ถ้าจำเป็นต้องแปลงแต่แปลงไม่ได้

### S-07: Audio Sync Service

**หน้าที่:** หา offset ของกล้องด้วย waveform cross-correlation

**Input:** extracted audio  
**Output:** `artifacts/sync_offsets.json`

**Failure policy:** `fail_job` สำหรับ multi-cam, `skip_and_warn` สำหรับ single-cam

## 8. Audio AI Services

### S-08: Voice Activity Detection Service

**หน้าที่:** ตรวจช่วง speech/silence จาก master audio

**Input:** master audio WAV  
**Output:** `artifacts/vad_segments.json`

**แนะนำ:** Silero VAD

**Failure policy:** `fail_job`

### S-09: Speaker Diarization Service

**หน้าที่:** ตรวจว่าเสียงช่วงไหนเป็นของ speaker คนไหน

**Input:** master audio WAV, `vad_segments.json`  
**Output:** `artifacts/diarization.json`

**แนะนำ:** Pyannote.audio

**Failure policy:** `fallback_to_default` โดยใช้ speaker เดียวทั้งคลิปได้ใน MVP

### S-10: Speaker-to-Camera Mapping Service

**หน้าที่:** map `speaker_id` เข้ากับ `asset_id`

**Input:** `diarization.json`, camera role จาก `job_manifest.json`, optional debug input จาก frontend  
**Output:** `artifacts/speaker_map.json`

**MVP:** ให้ frontend debug UI เลือก mapping เองก่อน

**Failure policy:** `fallback_to_default` ใช้ `Wide` หรือกล้องแรก

## 9. Vision AI Services

### S-11: Body Detection Service

**หน้าที่:** ตรวจตำแหน่งคนในวิดีโอ

**Input:** video หรือ proxy video  
**Output:** `artifacts/body_tracks.json`

**แนะนำ:** YOLO person detection

**ใช้โดย**

- Auto-Reframe Service
- Reaction Shot Service
- Speaker-to-Camera Mapping รุ่น advanced

**Failure policy:** `skip_and_warn`

### S-12: Face Detection & Tracking Service

**หน้าที่:** ตรวจและ track ใบหน้า

**Input:** video หรือ proxy video  
**Output:** `artifacts/face_tracks.json`

**ใช้โดย**

- Auto-Reframe Service
- Reaction Shot Service
- Speaker-to-Camera Mapping รุ่น advanced

**Failure policy:** `skip_and_warn`

**หมายเหตุ:** ไม่จำเป็นใน MVP ถ้าเริ่มจาก body detection หรือ manual mapping

## 10. Timeline Services

### S-13: Base Timeline Service

**หน้าที่:** สร้าง timeline ตั้งต้น

**Input:** `vad_segments.json`, `diarization.json`, `speaker_map.json`, `sync_offsets.json`  
**Output:** `artifacts/timeline_raw.json`

**Failure policy:** `fail_job`

### S-14: Timeline Conflict Resolver Service

**หน้าที่:** ตรวจ timeline หลัง plugin แก้ว่า render ได้จริง

**Input:** timeline จาก feature plugins  
**Output:** `artifacts/timeline_transformed.json`

**กฎหลัก**

- segment ห้ามเวลาติดลบ
- segment ห้าม overlap แบบผิด layout
- `source_asset_id` ต้องมีอยู่จริง
- manual override จาก debug UI ต้องชนะ AI/plugin
- ถ้า plugin สร้าง layout ที่ renderer ไม่รองรับ ให้ fallback เป็น `single` หรือ `wide`

**Failure policy:** `fail_job`

### S-15: Timeline Review Service

**หน้าที่:** ให้ debug frontend อ่าน/เขียน timeline สำหรับ manual override

**Input:** `timeline_transformed.json`  
**Output:** `artifacts/timeline_reviewed.json`

**หมายเหตุ:** เป็น debug helper ไม่ใช่ frontend product workflow เต็มรูปแบบ

## 11. Feature Services

### F-01: Remove Dead Air Service

**หน้าที่:** ตัด silence ที่ยาวเกิน threshold

**Input:** timeline, `vad_segments.json`  
**Output:** timeline artifact ใหม่

**Config**

```json
{
  "silence_threshold_seconds": 0.8,
  "keep_padding_before": 0.15,
  "keep_padding_after": 0.2
}
```

**Failure policy:** `fallback_to_default`

### F-02: Dynamic Split-Screen Service

**หน้าที่:** เปลี่ยน layout เป็น split-screen เมื่อมี speaker พูดทับกัน

**Input:** timeline, `diarization.json`, `speaker_map.json`  
**Output:** timeline artifact ใหม่

**Config**

```json
{
  "overlap_threshold_seconds": 0.4,
  "max_speakers_on_screen": 2,
  "fallback_layout": "wide"
}
```

**Failure policy:** `skip_and_warn`

### F-03: Reaction Shot Service

**หน้าที่:** ถ้าคนพูดพูดยาวเกิน threshold ให้ cut ไปหาคนฟัง 2-3 วินาที

**Input:** timeline, `speaker_map.json`, camera roles, optional `body_tracks.json` หรือ `face_tracks.json`  
**Output:** timeline artifact ใหม่

**Config**

```json
{
  "speaker_hold_threshold_seconds": 15.0,
  "reaction_duration_seconds": 2.5,
  "min_gap_between_reactions_seconds": 20.0,
  "listener_selection": "non_speaking_camera"
}
```

**กฎ**

- ถ้าไม่มีกล้องคนฟัง ให้ใช้ `Wide`
- ถ้าไม่มี `Wide` ให้ skip
- ห้ามแก้ segment ที่ `manual_override = true`

**Failure policy:** `skip_and_warn`

### F-04: Auto-Reframe Service

**หน้าที่:** สร้าง crop instruction สำหรับ output 9:16

**Input:** timeline, `body_tracks.json`, optional `face_tracks.json`, target aspect ratio  
**Output:** timeline artifact ใหม่ หรือ `reframe_plan.json`

**Failure policy:** `fallback_to_default` ใช้ center crop

### F-05: Auto-Audio Polish Service

**หน้าที่:** สร้าง audio filter config สำหรับ renderer

**Input:** master audio, optional music track, `vad_segments.json`  
**Output:** `artifacts/audio_filter_plan.json`

**Config**

```json
{
  "target_lufs": -16,
  "noise_gate_enabled": true,
  "auto_ducking_enabled": true
}
```

**Failure policy:** `skip_and_warn`

### F-06: Professional Export Service

**หน้าที่:** แปลง timeline เป็น FCPXML/EDL

**Input:** reviewed/final timeline, artifact manifest  
**Output:** `outputs/export.fcpxml`, `outputs/export.edl`

**Failure policy:** `skip_and_warn`

## 12. Renderer Services

### S-16: Render Plan Compiler Service

**หน้าที่:** แปลง timeline เป็น render plan ที่ FFmpeg Renderer เข้าใจ

**Input:** final timeline, artifact manifest, optional `audio_filter_plan.json`  
**Output:** `artifacts/render_plan.json`

**Failure policy:** `fail_job`

### S-17: FFmpeg Renderer Service

**หน้าที่:** render วิดีโอจริง

**Input:** `render_plan.json`  
**Output:** `outputs/final.mp4`

**ต้องรองรับใน MVP**

- single camera layout
- concat segments
- audio from master
- offset sync
- basic split-screen ถ้าเปิด feature
- center crop สำหรับ 9:16 fallback

**Failure policy:** `fail_job`

## 13. Debug Frontend

Frontend ในเฟสนี้เป็น debug tool ไม่ใช่ production app

### หน้าที่

- upload ไฟล์เข้า MinIO ผ่าน Orchestrator
- สร้าง `job_manifest.json`
- trigger pipeline ทั้งหมดหรือ trigger ทีละ service
- ดู `service_status.json`
- เปิดดู artifact JSON เช่น VAD, diarization, timeline
- แก้ `speaker_map.json` และ `timeline_reviewed.json`
- กด render
- ดาวน์โหลด `final.mp4`

### ไม่ต้องทำ

- auth
- role permission
- dashboard สวยงาม
- billing
- project management
- collaboration

## 14. Pipeline แนะนำ

```text
Debug Frontend
  -> Orchestrator API: create job
  -> MinIO: upload inputs
  -> Validation Service
  -> Media Metadata Service
  -> Audio Extraction Service
  -> Media Normalization Service
  -> Audio Sync Service
  -> Voice Activity Detection Service
  -> Speaker Diarization Service
  -> Speaker-to-Camera Mapping Service
  -> Body Detection Service                  optional
  -> Face Detection & Tracking Service       optional
  -> Base Timeline Service
  -> Feature Chain
       -> Remove Dead Air                    optional
       -> Dynamic Split-Screen               optional
       -> Reaction Shot                      optional
       -> Auto-Reframe                       optional/required for 9:16
       -> Auto-Audio Polish                  optional
  -> Timeline Conflict Resolver Service
  -> Debug Frontend: optional review/edit
  -> Render Plan Compiler Service
  -> FFmpeg Renderer Service
  -> Professional Export Service             optional
```

## 15. การแบ่งทีม

### Team A: Orchestrator & Contracts

- Orchestrator API
- MinIO object layout
- manifest schema
- service status schema
- service runner
- failure policy

### Team B: Media Services

- Media Metadata Service
- Audio Extraction Service
- Media Normalization Service
- Audio Sync Service

### Team C: Audio AI Services

- VAD Service
- Speaker Diarization Service
- Speaker-to-Camera Mapping MVP
- Auto-Audio Polish Service

### Team D: Vision AI Services

- Body Detection Service
- Face Detection & Tracking Service
- Auto-Reframe Service

### Team E: Timeline & Feature Services

- Base Timeline Service
- Remove Dead Air Service
- Dynamic Split-Screen Service
- Reaction Shot Service
- Timeline Conflict Resolver Service

### Team F: Renderer & Export

- Render Plan Compiler Service
- FFmpeg Renderer Service
- Professional Export Service

### Team G: Debug Frontend

- upload/debug page
- job status viewer
- artifact JSON viewer
- speaker map editor
- timeline editor แบบง่าย
- output downloader

## 16. MVP Scope แนะนำ

ลำดับที่ควรทำก่อน:

1. MinIO layout และ manifest schema
2. Orchestrator API เรียก service ผ่าน HTTP ได้
3. Debug Frontend สำหรับ upload และ trigger job
4. Validation Service
5. Media Metadata Service
6. Audio Extraction Service
7. VAD Service
8. Speaker Diarization Service แบบ fallback ได้
9. Speaker-to-Camera Mapping ผ่าน debug UI
10. Base Timeline Service
11. Render Plan Compiler Service
12. FFmpeg Renderer Service แบบ single layout
13. Remove Dead Air Service
14. Reaction Shot Service
15. Split-Screen Service
16. Auto-Reframe Service
17. Professional Export Service

## 17. Definition of Done สำหรับทุก Service

ทุก service ต้องส่งมอบ:

- `README.md` ของ service
- HTTP API spec ของ `/run`
- input artifact ที่ต้องใช้
- output artifact ที่สร้าง
- config schema
- failure policy
- sample job สำหรับทดสอบ
- unit test หรือ integration test อย่างน้อย happy path
- log ที่อ่านจาก `logs/{service_id}.log` ได้
- ไม่เขียน output ทับของ service อื่น

## 18. กฎเพื่อให้ถอด Service แล้วระบบไม่พัง

- Service คุยกันผ่าน MinIO artifact และ HTTP contract เท่านั้น
- Optional service ต้อง skip ได้
- Required service fail แล้วต้องหยุด job ชัดเจน
- Artifact output ต้องมี path คงที่หรือประกาศใน `artifact_manifest.json`
- Timeline ต้องผ่าน Conflict Resolver ก่อน render
- Renderer อ่านจาก `render_plan.json` เท่านั้น
- Debug Frontend ห้ามเป็น dependency ของ pipeline
- Orchestrator ต้องรัน pipeline ได้แม้ไม่เปิด frontend
- Manual override จาก debug frontend ต้องถูกเก็บเป็น artifact แยก ไม่เขียนทับ raw timeline
