# Phase 1 Todo - 16:9 to 9:16 Smooth Reframe

**Goal:** รับวิดีโอ 1 ไฟล์แบบ 16:9 แล้วแปลงเป็นวิดีโอ 9:16 โดย crop ตามคน/subject แบบ smooth  
**Scope:** ทำให้ใช้งานได้จริงก่อน ยังไม่ต้องมี multi-cam, speaker diarization, reaction shot, split-screen, auth, database

## 1. Phase 1 Output ที่ต้องได้

ผู้ใช้สามารถ:

1. Upload วิดีโอ 16:9 จำนวน 1 ไฟล์ผ่าน Debug Frontend
2. สร้าง job และเลือก output เป็น 9:16
3. ให้ระบบ detect ตำแหน่งคนในวิดีโอ
4. สร้าง reframe path ที่ crop ตาม subject
5. ทำ smoothing/easing ไม่ให้กล้อง virtual กระตุก
6. render ออกมาเป็น `.mp4` แนวตั้ง 9:16
7. ดาวน์โหลดไฟล์ output ได้

## 2. Stack สำหรับ Phase 1

```text
Debug Frontend
  -> Orchestrator API
      -> MinIO
      -> Validation Service
      -> Media Metadata Service
      -> Proxy/Frame Sampling Service
      -> Body Detection Service
      -> Track Interpolation Service
      -> Reframe Planning Service
      -> Easing/Smoothing Service
      -> Render Plan Compiler Service
      -> FFmpeg Renderer Service
```

## 3. MinIO Layout สำหรับ Phase 1

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
    body_detection.log
    reframe_planning.log
    easing_smoothing.log
    renderer.log
```

## 4. Service Todo

### S-01: Debug Frontend

**Purpose:** ใช้ debug pipeline ไม่ใช่ product UI

Todo:

- Upload วิดีโอ 1 ไฟล์
- เลือก target output เป็น `9:16`
- ปุ่ม `Create Job`
- ปุ่ม `Run Full Pipeline`
- แสดง `service_status.json`
- แสดงลิงก์ artifact สำคัญ เช่น `body_tracks_raw.json`, `reframe_plan_smooth.json`
- แสดง video output หลัง render
- ปุ่ม download `final_9x16.mp4`

Done when:

- สามารถ upload, trigger job, ดู status, download output ได้จากหน้าเดียว

### S-02: Orchestrator API

**Purpose:** สร้าง job และเรียก service ตามลำดับ

Todo:

- สร้าง `job_id`
- เขียน `job_manifest.json`
- เขียน `service_status.json`
- upload ไฟล์เข้า MinIO path `jobs/{job_id}/input/source.mp4`
- เรียก service ตาม pipeline
- ถ้า service fail ให้ update status พร้อม error
- update `artifact_manifest.json` หลัง service สร้าง output

Phase 1 Pipeline:

```text
validation
  -> media_metadata
  -> proxy_frame_sampling
  -> body_detection
  -> track_interpolation
  -> reframe_planning
  -> easing_smoothing
  -> render_plan_compiler
  -> ffmpeg_renderer
```

Done when:

- เรียก pipeline ทั้งหมดได้ด้วย job เดียว
- ไม่ต้องมี database
- restart แล้วอ่านสถานะจาก MinIO ได้

### S-03: Validation Service

**Purpose:** ตรวจ input ก่อน render

Todo:

- ตรวจว่ามี input video แค่ 1 ไฟล์
- ตรวจว่า input เป็น video ที่อ่านได้
- ตรวจ aspect ratio เป็น 16:9 หรือใกล้เคียง
- ตรวจ target output เป็น 9:16
- ตรวจว่า duration ไม่เป็น 0
- ถ้า metadata ยังไม่มี ให้รอ Media Metadata Service หรือเรียก ffprobe เบื้องต้นได้

Done when:

- invalid input ต้องหยุด job พร้อม error อ่านรู้เรื่อง

### S-04: Media Metadata Service

**Purpose:** อ่านข้อมูลวิดีโอ

Todo:

- ใช้ `ffprobe` อ่าน width, height, fps, duration, codec, rotation metadata
- เขียน `artifacts/metadata.json`
- normalize ค่า rotation ถ้าวิดีโอมี metadata หมุนภาพ
- คำนวณ source aspect ratio
- คำนวณ target crop size สำหรับ 9:16

Output example:

```json
{
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "duration": 120.4,
  "source_aspect_ratio": "16:9",
  "target_aspect_ratio": "9:16",
  "target_resolution": {
    "width": 1080,
    "height": 1920
  }
}
```

Done when:

- metadata เพียงพอสำหรับ detection และ render

### S-05: Proxy/Frame Sampling Service

**Purpose:** เตรียม input ให้ AI detect เร็วขึ้น

Todo:

- สร้าง proxy video ขนาดเล็ก เช่น height `360` หรือ `540`
- sample frame ทุก `0.2s` หรือ `5 fps` สำหรับ detection
- เขียน `artifacts/proxy.mp4`
- เขียน `artifacts/sampled_frames.json`
- เก็บ mapping ระหว่าง frame index กับ timestamp

Config:

```json
{
  "sample_fps": 5,
  "proxy_height": 540
}
```

Done when:

- ได้ proxy ที่เบาพอให้ detection รันเร็ว
- timestamp mapping ถูกต้อง

### S-06: Body Detection Service

**Purpose:** หา subject/person ในแต่ละ sampled frame

Todo:

- โหลด proxy หรือ sampled frames จาก MinIO
- รัน person detection เช่น YOLO
- เลือก bounding box หลักของคนในภาพ
- ถ้ามีหลายคน ให้เลือก strategy:
  - box ใหญ่สุด
  - center ใกล้ crop center ล่าสุด
  - confidence สูงสุด
- เขียน `artifacts/body_tracks_raw.json`
- ใส่ confidence ทุก detection
- mark frame ที่ detect ไม่เจอเป็น missing

Output example:

```json
{
  "tracks": [
    {
      "t": 0.0,
      "bbox": {
        "x": 820,
        "y": 120,
        "w": 420,
        "h": 860
      },
      "center": {
        "x": 1030,
        "y": 550
      },
      "confidence": 0.91
    }
  ]
}
```

Done when:

- ได้ตำแหน่งคนตาม timestamp
- ถ้า detect ไม่เจอ ระบบยังไปต่อด้วย fallback center crop ได้

### S-07: Track Interpolation Service

**Purpose:** เติมช่วง detection หายและทำ track ต่อเนื่องก่อนสร้าง crop

Todo:

- อ่าน `body_tracks_raw.json`
- interpolate ช่วงที่ detection หายสั้น ๆ เช่นไม่เกิน `1.0s`
- ถ้าหายนาน ให้ fallback ไป center crop หรือ hold ตำแหน่งล่าสุดตาม config
- remove outlier ที่กระโดดผิดปกติ
- เขียน `artifacts/body_tracks_interpolated.json`

Config:

```json
{
  "max_gap_fill_seconds": 1.0,
  "max_center_jump_per_second": 600,
  "missing_strategy": "hold_then_center"
}
```

Done when:

- track ไม่มีจุดกระโดดหนักจาก false detection

### S-08: Reframe Planning Service

**Purpose:** สร้างแผน crop 9:16 จากตำแหน่ง subject

Todo:

- อ่าน metadata และ `body_tracks_interpolated.json`
- คำนวณ crop window 9:16 บน source video
- ให้ crop ตามแกน X เป็นหลักสำหรับ source 16:9
- clamp crop ไม่ให้ออกนอกขอบวิดีโอ
- ใส่ subject framing rule เช่นให้หน้า/ลำตัวอยู่กลางภาพหรือ rule-of-thirds
- สร้าง keyframe crop position ตาม timestamp
- เขียน `artifacts/reframe_plan_raw.json`

Crop rule พื้นฐาน:

- ถ้า source 1920x1080 และ target 9:16 บนความสูงเดิม 1080:
  - crop height = `1080`
  - crop width = `607.5` หรือปัดเป็นเลขคู่ เช่น `608`
  - crop x = subject center x - crop width / 2
  - crop y = `0`

Output example:

```json
{
  "crop_width": 608,
  "crop_height": 1080,
  "keyframes": [
    {
      "t": 0.0,
      "x": 650,
      "y": 0,
      "confidence": 0.91
    }
  ]
}
```

Done when:

- ได้ crop path ที่ถูก aspect ratio 9:16
- crop ไม่หลุดขอบวิดีโอ

### S-09: Easing/Smoothing Service

**Purpose:** ทำให้ virtual camera เคลื่อนนุ่ม ไม่กระตุก

Todo:

- อ่าน `reframe_plan_raw.json`
- smooth crop x/y ด้วย filter เช่น moving average, exponential smoothing หรือ Kalman filter
- จำกัดความเร็วสูงสุดของ crop movement
- จำกัด acceleration เพื่อลดอาการกระชาก
- ใส่ easing เวลาเปลี่ยน target position เช่น `easeInOutCubic`
- สร้าง keyframe ที่ FFmpeg ใช้ได้
- เขียน `artifacts/reframe_plan_smooth.json`

Config:

```json
{
  "smoothing_method": "exponential",
  "smoothing_strength": 0.82,
  "max_velocity_px_per_second": 700,
  "max_acceleration_px_per_second2": 1600,
  "easing": "easeInOutCubic",
  "dead_zone_px": 80
}
```

กฎสำคัญ:

- ถ้า subject ขยับเล็กน้อยใน `dead_zone_px` ไม่ต้องขยับ crop
- ถ้า target เปลี่ยนมาก ให้ค่อย ๆ pan ไม่ jump
- ถ้า detection หายสั้น ๆ ให้ hold crop เดิม
- ถ้า detection หายนาน ให้ ease กลับ center crop
- x/y ต้อง clamp หลัง smoothing ทุกครั้ง

Easing function ที่ควรมี:

```text
linear
easeOutCubic
easeInOutCubic
easeInOutSine
```

Done when:

- crop path ดูนุ่มเมื่อ preview
- ไม่มี frame ที่ crop กระโดดแบบเห็นชัด
- ไม่มี crop ออกนอก source video

### S-10: Render Plan Compiler Service

**Purpose:** แปลง reframe plan เป็น render plan

Todo:

- อ่าน `reframe_plan_smooth.json`
- อ่าน `metadata.json`
- สร้าง `artifacts/render_plan.json`
- กำหนด target resolution เช่น `1080x1920`
- กำหนด crop expression หรือ keyframe file สำหรับ renderer
- กำหนด audio copy หรือ transcode policy

Output example:

```json
{
  "input": "jobs/job_001/input/source.mp4",
  "output": "jobs/job_001/outputs/final_9x16.mp4",
  "target_resolution": {
    "width": 1080,
    "height": 1920
  },
  "crop_plan": "jobs/job_001/artifacts/reframe_plan_smooth.json",
  "video_codec": "libx264",
  "audio_codec": "aac"
}
```

Done when:

- renderer ไม่ต้องรู้ logic ของ AI หรือ smoothing
- renderer อ่านเฉพาะ render plan แล้วทำงานได้

### S-11: FFmpeg Renderer Service

**Purpose:** render output 9:16 จริง

Todo:

- อ่าน `render_plan.json`
- download source video และ crop plan จาก MinIO
- สร้าง FFmpeg command
- crop ตาม keyframe หรือ expression
- scale output เป็น `1080x1920`
- encode เป็น H.264/AAC
- upload `outputs/final_9x16.mp4` กลับ MinIO

MVP render strategy:

- ถ้า keyframe crop ต่อ frameยังยาก ให้เริ่มจากสร้าง segment สั้น ๆ ที่ crop position คงที่ แล้ว concat
- ถ้าต้องการ smooth จริงขึ้น ให้ใช้ FFmpeg filter expression หรือสร้าง crop command จาก interpolated per-frame position

Done when:

- output เป็น 9:16
- เล่นได้ทั้งภาพและเสียง
- ความยาวใกล้เคียง input
- movement ไม่กระตุกชัดเจน

## 5. Parallel Todo Board

รายการนี้เปลี่ยนเป็น Markdown task list เพื่อให้ติ๊กสถานะงานได้ตรง ๆ โดยเปลี่ยน `[ ]` เป็น `[x]` เมื่อเสร็จ

- [x] P1-A01: กำหนด contract กลางของ `job_manifest.json`, `artifact_manifest.json`, `service_status.json`
  Owner: Orchestrator | Write Scope: `contracts/`, docs หรือ schema กลาง | Depends on: None | Deliverable: JSON schema + sample job
- [x] P1-A02: กำหนด MinIO object layout และ helper สำหรับ read/write artifact
  Owner: Orchestrator | Write Scope: Orchestrator service เท่านั้น | Depends on: P1-A01 | Deliverable: helper upload/download/list artifact
- [x] P1-A03: ทำ Orchestrator API สำหรับ create job และ run pipeline
  Owner: Orchestrator | Write Scope: Orchestrator service เท่านั้น | Depends on: P1-A01, P1-A02 | Deliverable: API create job/run job/status
- [x] P1-A04: ทำ service runner สำหรับเรียก `/run` ของแต่ละ service ตามลำดับ
  Owner: Orchestrator | Write Scope: Orchestrator service เท่านั้น | Depends on: P1-A03 | Deliverable: pipeline runner + failure handling
- [ ] P1-B01: ทำ Debug Frontend หน้า upload + create job
  Owner: Frontend | Write Scope: Debug frontend เท่านั้น | Depends on: P1-A03 | Deliverable: upload และ create job ได้
- [ ] P1-B02: ทำ Debug Frontend หน้า status/artifact viewer
  Owner: Frontend | Write Scope: Debug frontend เท่านั้น | Depends on: P1-A01, P1-A03 | Deliverable: ดู `service_status.json` และ artifact links ได้
- [ ] P1-B03: ทำ Debug Frontend หน้า preview/download output
  Owner: Frontend | Write Scope: Debug frontend เท่านั้น | Depends on: P1-A03, P1-H02 | Deliverable: preview/download `final_9x16.mp4`
- [ ] P1-C01: ทำ Validation Service
  Owner: Validation | Write Scope: Validation service เท่านั้น | Depends on: P1-A01 | Deliverable: `/run` validate input/job config
- [ ] P1-C02: ทำ Media Metadata Service ด้วย `ffprobe`
  Owner: Media | Write Scope: Media metadata service เท่านั้น | Depends on: P1-A01 | Deliverable: `metadata.json`
- [ ] P1-C03: ทำ Proxy/Frame Sampling Service
  Owner: Media | Write Scope: Proxy/frame sampling service เท่านั้น | Depends on: P1-C02 | Deliverable: `proxy.mp4`, `sampled_frames.json`
- [ ] P1-D01: เลือก model และทำ Body Detection Service skeleton
  Owner: Vision AI | Write Scope: Body detection service เท่านั้น | Depends on: P1-A01 | Deliverable: `/run` อ่าน proxy และเขียน output mock ได้
- [ ] P1-D02: ทำ body detection จริงบน sampled frames/proxy
  Owner: Vision AI | Write Scope: Body detection service เท่านั้น | Depends on: P1-C03, P1-D01 | Deliverable: `body_tracks_raw.json`
- [ ] P1-D03: ทำ fallback เมื่อ detect ไม่เจอ
  Owner: Vision AI | Write Scope: Body detection service เท่านั้น | Depends on: P1-D02 | Deliverable: missing frames + confidence policy
- [ ] P1-E01: ทำ Track Interpolation Service
  Owner: Reframe | Write Scope: Track interpolation service เท่านั้น | Depends on: P1-D02 | Deliverable: `body_tracks_interpolated.json`
- [ ] P1-E02: ทำ outlier removal และ missing strategy
  Owner: Reframe | Write Scope: Track interpolation service เท่านั้น | Depends on: P1-E01 | Deliverable: track ที่ไม่กระโดดแรง
- [ ] P1-F01: ทำ Reframe Planning Service
  Owner: Reframe | Write Scope: Reframe planning service เท่านั้น | Depends on: P1-C02, P1-E01 | Deliverable: `reframe_plan_raw.json`
- [ ] P1-F02: ทำ crop clamp และ subject framing rule
  Owner: Reframe | Write Scope: Reframe planning service เท่านั้น | Depends on: P1-F01 | Deliverable: crop ไม่หลุดขอบ
- [ ] P1-G01: ทำ easing function library
  Owner: Smoothing | Write Scope: Easing/smoothing service เท่านั้น | Depends on: P1-A01 | Deliverable: `linear`, `easeOutCubic`, `easeInOutCubic`, `easeInOutSine`
- [ ] P1-G02: ทำ Easing/Smoothing Service
  Owner: Smoothing | Write Scope: Easing/smoothing service เท่านั้น | Depends on: P1-F01, P1-G01 | Deliverable: `reframe_plan_smooth.json`
- [ ] P1-G03: ทำ velocity/acceleration limit และ dead zone
  Owner: Smoothing | Write Scope: Easing/smoothing service เท่านั้น | Depends on: P1-G02 | Deliverable: crop path smooth และ clamp แล้ว
- [ ] P1-H01: ทำ Render Plan Compiler Service
  Owner: Renderer | Write Scope: Render plan compiler service เท่านั้น | Depends on: P1-C02, P1-G02 | Deliverable: `render_plan.json`
- [ ] P1-H02: ทำ FFmpeg Renderer Service แบบ center crop/static crop ก่อน
  Owner: Renderer | Write Scope: FFmpeg renderer service เท่านั้น | Depends on: P1-H01 | Deliverable: output 9:16 เล่นได้
- [ ] P1-H03: ทำ FFmpeg Renderer ใช้ smooth crop plan
  Owner: Renderer | Write Scope: FFmpeg renderer service เท่านั้น | Depends on: P1-G03, P1-H02 | Deliverable: output 9:16 ที่ pan ตาม crop plan
- [ ] P1-I01: ทำ sample input/output fixture สำหรับทุก service
  Owner: QA/Integration | Write Scope: `fixtures/` หรือ test data เท่านั้น | Depends on: P1-A01 | Deliverable: sample job + sample artifact
- [ ] P1-I02: ทำ integration test pipeline ด้วย mock service
  Owner: QA/Integration | Write Scope: integration test เท่านั้น | Depends on: P1-A04, P1-I01 | Deliverable: pipeline วิ่งครบด้วย mock artifact
- [ ] P1-I03: ทำ end-to-end test ด้วยวิดีโอจริงสั้น ๆ
  Owner: QA/Integration | Write Scope: integration test เท่านั้น | Depends on: P1-D02, P1-G03, P1-H03 | Deliverable: output ผ่าน acceptance criteria

Source of truth for P1-A01 contract files lives in `contracts/CONTRACTS.md` and the JSON Schemas under `contracts/`.

สถานะล่าสุด: P1-A01, P1-A02, P1-A03, และ P1-A04 เสร็จแล้ว โดย P1-A04 เพิ่ม HTTP service runner ที่เรียก `/run` ตามลำดับ, register artifacts/warnings, handle hard-fail ต่อ step, และยัง fallback เป็น mock runner เมื่อยังไม่ config service endpoints.

### งานที่ทำพร้อมกันได้ทันที

- P1-A01, P1-B01, P1-C01, P1-D01, P1-G01, P1-I01 ทำพร้อมกันได้ แต่ทุกคนต้องยึด sample contract เดียวกัน
- P1-C02 ทำคู่กับ P1-C01 ได้ เพราะใช้ input video เหมือนกันแต่ output คนละ artifact
- P1-H02 เริ่มทำแบบ static/center crop ได้ก่อน โดยยังไม่ต้องรอ AI หรือ smoothing
- P1-B02 ทำด้วย mock `service_status.json` ได้ก่อน แล้วค่อยต่อ API จริงภายหลัง

### งานที่ต้องเรียงลำดับ

- P1-A01 ต้องเสร็จก่อนงานที่เขียน/อ่าน manifest จริงทุกตัว
- P1-A03 ต้องเสร็จก่อน Debug Frontend ต่อ create job จริง
- P1-C02 ต้องเสร็จก่อน P1-C03, P1-F01, P1-H01 เพราะต้องใช้ metadata
- P1-C03 ต้องเสร็จก่อน P1-D02 เพราะ body detection ใช้ proxy/sampled frames
- P1-D02 ต้องเสร็จก่อน P1-E01 เพราะ interpolation ต้องใช้ raw body tracks
- P1-E01 ต้องเสร็จก่อน P1-F01 เพราะ reframe planning ต้องใช้ interpolated tracks
- P1-F01 ต้องเสร็จก่อน P1-G02 เพราะ smoothing ต้องใช้ raw reframe plan
- P1-G02 ต้องเสร็จก่อน P1-H01 เพราะ render plan ต้องชี้ไปที่ smooth crop plan
- P1-H01 ต้องเสร็จก่อน P1-H02/P1-H03 เพราะ renderer อ่านจาก render plan เท่านั้น
- P1-H03 ต้องเสร็จก่อน P1-I03 เพราะ end-to-end test ต้องใช้ renderer จริง

### จุดที่อาจทับกันและต้องตกลงก่อน

- `reframe_plan_raw.json` และ `reframe_plan_smooth.json`: ทีม Reframe กับ Smoothing ต้องตกลง schema ก่อนเริ่ม P1-F01/P1-G02
- `render_plan.json`: ทีม Smoothing/Renderer ต้องตกลงว่าจะส่ง crop เป็น keyframe list, per-frame list, หรือ expression file ก่อนเริ่ม P1-H01
- `body_tracks_raw.json`: ทีม Vision AI กับ Track Interpolation ต้องตกลง coordinate ว่าเป็น source resolution หรือ proxy resolution ก่อนเริ่ม P1-D02/P1-E01
- MinIO helper: ทุก service ต้องใช้ path convention เดียวกัน ห้ามกำหนด object key เองแบบหลุดจาก `jobs/{job_id}/...`
- FFmpeg crop strategy: ถ้า H03 ใช้ per-frame expression ยาก ให้ตกลง fallback เป็น segment-based render ก่อน เพื่อไม่ block end-to-end

## 6. Phase 1 Pipeline

```text
Create Job
  -> Upload source.mp4
  -> Validation Service
  -> Media Metadata Service
  -> Proxy/Frame Sampling Service
  -> Body Detection Service
  -> Track Interpolation Service
  -> Reframe Planning Service
  -> Easing/Smoothing Service
  -> Render Plan Compiler Service
  -> FFmpeg Renderer Service
  -> Download final_9x16.mp4
```

## 7. Phase 1 Feature ที่ยังไม่ทำ

- multi-camera
- audio sync
- speaker diarization
- speaker-to-camera mapping
- remove dead air
- reaction shot
- split-screen
- professional export
- timeline editor เต็มรูปแบบ
- auth
- database

## 8. Risk / จุดที่ต้องระวัง

- Detection กระพริบ ทำให้ crop กระตุก
- Subject หลุดจาก frame ตอน detection หาย
- Crop ขยับเร็วเกินจนดูเวียนหัว
- Crop expression ใน FFmpeg อาจซับซ้อน ถ้าทำต่อ frame
- วิดีโอที่มีหลายคนต้องเลือก subject ให้คงที่
- วิดีโอที่คนอยู่ริมซ้าย/ขวาอาจ crop ติดขอบ ต้อง clamp ดี ๆ
- วิดีโอที่มี camera cut ภายในคลิปเดียว อาจต้อง reset smoothing เมื่อ scene เปลี่ยน

## 9. Acceptance Criteria

Phase 1 ถือว่าผ่านเมื่อ:

- ใช้วิดีโอ 16:9 หนึ่งไฟล์เป็น input ได้
- ระบบ output เป็น mp4 9:16
- subject หลักอยู่ใน crop เป็นส่วนใหญ่
- crop movement smooth ไม่มี jump ชัดเจน
- ถ้า detect ไม่เจอ ระบบ fallback center crop ได้
- ทุก service เขียน artifact ของตัวเองลง MinIO
- Orchestrator รัน pipeline ได้โดยไม่ต้องใช้ frontend
- Debug Frontend ใช้ดู status และดาวน์โหลด output ได้
