# Hyperframes Finishing Service - Development Tasks

## Objective

เอกสารนี้แตกงานจาก [prd-hyperframe .md](./prd-hyperframe%20.md) ให้อยู่ในรูป task development plan ที่ทีมสามารถใช้ลงมือพัฒนาได้จริงสำหรับ **Standalone Hyperframes Finishing Service** โดยเน้น V1 ก่อน และแยกงานตามลำดับ dependency ให้ชัดเจน

เป้าหมายของ V1:

- รับวิดีโอเข้าโดยตรงจากหน้า frontend แยก
- ตรวจ orientation และ route ไปยัง `vertical` หรือ `horizontal` template family
- render ด้วย Hyperframes เป็น MP4
- รองรับ logo overlay และ subtitle input แบบ JSON เป็นอย่างน้อย
- ทำงานแยกจาก pipeline เดิมของ Smart Cut Reel

## Scope Summary

### In Scope (V1)

- Standalone service สำหรับ upload -> create job -> render -> download
- API service สำหรับ job lifecycle
- Render worker สำหรับ Hyperframes execution
- Vertical Input Template
- Horizontal Input Template
- Orientation detection + manual override
- Logo overlay
- Subtitle JSON import
- Basic artifact/debug output

### Out Of Scope (V1)

- เชื่อม orchestrator เดิมแบบเต็มรูปแบบ
- ASR generation ภายใน service นี้
- face-aware logo placement
- multi-user collaborative editor
- advanced template marketplace

## Working Assumptions

- Backend orchestration หลักของ repo ยังเป็น Python-centric
- Hyperframes runtime อาจต้องใช้ Node execution path แยกจาก Python API/worker layer
- Output หลักของ V1 คือ MP4 (H.264)
- Subtitle format หลักคือ JSON แบบ word-level timestamps
- SRT เป็น fallback import format เท่านั้น

## Current Status Snapshot

สถานะ ณ ตอนนี้อิงจาก implementation ที่มีอยู่จริงใน repo:

- Done: service skeleton, API routes, job storage, status flow, output endpoint, worker loop, frontend studio route/page, upload form, status screen, artifact/debug view, targeted tests, developer runbook, real Hyperframes CLI render bridge, basic subtitle parsing, real vertical/horizontal smoke renders
- Partial: subtitle schema ถูก mirror เป็น typed model/validation helper บน frontend แล้ว แต่ยังไม่ได้แชร์จาก source เดียวกันข้าม Python/TypeScript, template descriptor files ฝั่ง TypeScript ยังเป็น scaffold มากกว่าตัวที่ควบคุม render จริง, intro/outro ยังไม่มี transition layer
- Pending: richer subtitle validation/highlight rules, reusable fixture media files, operational limits, failure-case API coverage

Validation ล่าสุด:

- Targeted backend tests ของ `services/hyperframes_finishing` ผ่านทั้งหมด 17 tests รวม render smoke test จริง
- manual smoke render ผ่านจริงสำหรับทั้ง horizontal และ vertical inputs ผ่าน `HyperframesCliRenderExecutor`
- frontend/backend files ที่เพิ่มใหม่ไม่มี editor errors
- frontend `tsconfig` typecheck ผ่านหลังเพิ่ม subtitle validation flow และ typed route fixes

## Suggested Delivery Phases

### Phase HF-00: Foundations

เป้าหมาย: วางโครง service, contracts และ technical skeleton ให้เริ่มงานได้โดยไม่แก้หลายรอบ

### Phase HF-01: Job API + Storage

เป้าหมาย: สร้าง API สำหรับรับงาน render, เก็บ job state, เก็บ assets, เปิด status polling

### Phase HF-02: Hyperframes Render Core

เป้าหมาย: ทำ worker และ render pipeline ให้ render งานพื้นฐานได้จริง

### Phase HF-03: Template Routing + Vertical/Horizontal Templates

เป้าหมาย: route input ให้ถูก family และ render ผ่าน template แยกกันได้

### Phase HF-04: Frontend Studio V1

เป้าหมาย: ทำหน้า upload/configure/status/download สำหรับ service ใหม่

### Phase HF-05: Validation, Fixtures, Hardening

เป้าหมาย: เพิ่ม tests, smoke validation, debug artifacts, และ operational guardrails

## Dependency Map

- HF-00 ต้องเสร็จก่อน HF-01 และ HF-02
- HF-01 และ HF-02 เดินคู่ขนานได้บางส่วน หลัง contract ชัด
- HF-03 ขึ้นกับ HF-02
- HF-04 ขึ้นกับ HF-01 เป็นอย่างน้อย
- HF-05 ทำต่อจาก HF-02, HF-03, HF-04

## Detailed Tasks

## Phase HF-00: Foundations

### HF-00-01: Create service folder skeleton

- [x] สร้างโครงสร้าง service ใหม่ใต้ `services/hyperframes_finishing/`
- [x] แยกโฟลเดอร์ `api`, `domain`, `worker`, `storage`, `tests`
- [x] ตัดสินใจว่าจะวาง Hyperframes runtime ร่วมใน service เดียวหรือแยกเป็น Node submodule

Definition of done:

- มีโครงสร้างโฟลเดอร์เริ่มต้นตาม PRD
- มีไฟล์ README ย่อยของ service อธิบาย local run path เบื้องต้น

Validation:

- เปิด tree แล้วเห็นโครงสร้างครบ
- ไม่มี path conflict กับ services เดิม

### HF-00-02: Define service boundary and runtime split

- [x] สรุปว่า API layer ใช้ Python หรือ Node เป็นหลัก
- [x] สรุป interface ระหว่าง API layer กับ Hyperframes renderer
- [x] ระบุ strategy สำหรับ queue/job execution ใน local dev และ production-like dev

Definition of done:

- มี decision note ชัดว่า render เรียกผ่าน function, subprocess, internal HTTP หรือ queue

Validation:

- ทีม backend กับ frontend ตีความตรงกัน

### HF-00-03: Freeze V1 request/response contract

- [x] กำหนด `job request` fields สำหรับ source video, intro/outro, logo, subtitle, template override
- [x] กำหนด `job response` fields สำหรับ job creation และ job status
- [x] กำหนด enum ชุดแรกของ `template_family`, `job_status`, `error_code`

Definition of done:

- มี contract ที่นำไปใช้ใน API schema และ frontend form ได้ทันที

Validation:

- contract ครอบคลุมกรณี `auto`, `vertical`, `horizontal`

### HF-00-04: Define normalized render spec

- [x] ออกแบบ internal normalized render spec กลาง
- [x] ระบุ structure ของ `assets`, `composition`, `template_family`, `template_variant`
- [x] กำหนด field ที่ worker ต้องใช้ขั้นต่ำ

Definition of done:

- API layer และ render worker ใช้ spec เดียวกัน

Validation:

- สามารถประกอบตัวอย่าง spec จาก PRD ได้ครบ

### HF-00-05: Define subtitle JSON schema

- [x] สรุป schema สำหรับ segment + word-level timestamps
- [x] ระบุ validation rules เช่น `start < end`, words อยู่ในช่วง segment
- [x] กำหนด fallback behavior เมื่อเป็น SRT หรือไม่มี word-level timing

Status note:

- backend มี typed subtitle models แล้วและ render layer/create-job ใช้ validation เดียวกัน; ฝั่ง frontend ยังไม่ได้ share model เดียวกันตรง ๆ จึงยังเหลืองาน contract unification อีกขั้น

Definition of done:

- มี schema หรือ typed model ที่ frontend/backend ใช้อ้างอิงตรงกัน

Validation:

- frontend upload flow validate subtitle file ได้ก่อนยิง API และสรุปว่าเป็น word-level หรือ phrase-level fallback ได้

- มี sample subtitle JSON อย่างน้อย 2 แบบ: word-level, phrase-level fallback

## Phase HF-01: Job API + Storage

### HF-01-01: Implement create-job API

- [x] สร้าง endpoint สำหรับรับ multipart/form-data หรือ equivalent upload flow
- [x] รองรับ fields ตาม V1 contract
- [x] validate file presence และ basic payload correctness

Definition of done:

- client เรียกสร้าง job ได้และได้ `job_id` กลับ

Validation:

- test create-job สำเร็จเมื่อมี source video
- test fail เมื่อ request ขาด source video

### HF-01-02: Implement job status API

- [x] สร้าง endpoint สำหรับดู job status
- [x] แสดง `created`, `queued`, `rendering`, `completed`, `failed`
- [x] รองรับ progress field เบื้องต้น

Definition of done:

- frontend poll status ได้

Validation:

- status เปลี่ยนตาม workflow จริง

### HF-01-03: Implement output download API

- [x] สร้าง endpoint สำหรับดึง output MP4
- [x] รองรับกรณี output ยังไม่พร้อม
- [x] กำหนด content headers ให้ถูกต้อง

Definition of done:

- output ดาวน์โหลดได้หลัง render เสร็จ

Validation:

- request output ก่อนงานเสร็จต้องได้ response ที่ตีความได้ชัด

### HF-01-04: Implement asset storage abstraction

- [x] สร้าง abstraction สำหรับเก็บ source video, intro/outro, logo, subtitle, output
- [x] ระบุ object key naming convention
- [x] รองรับ local filesystem mode สำหรับ dev/test

Definition of done:

- API layer เก็บ asset และส่ง reference ไป worker ได้

Validation:

- local upload -> stored object path -> worker read path ทำงานครบ

### HF-01-05: Implement job store abstraction

- [x] เก็บ status, timestamps, template routing result, output URL, error summary
- [x] รองรับ update state แบบปลอดภัยระหว่าง worker กับ API
- [x] รองรับ retry-safe update ขั้นต้น

Definition of done:

- สถานะ job ไม่หายและ query ได้ซ้ำ

Validation:

- create/update/read job state ผ่าน tests ได้

## Phase HF-02: Hyperframes Render Core

### HF-02-01: Bootstrap Hyperframes render runtime

- [x] ติดตั้ง dependency ที่จำเป็นสำหรับ Hyperframes
- [x] สร้าง minimal render entrypoint
- [x] ยืนยันว่า render video output ได้จาก fixture ง่ายๆ

Status note:

- ตอนนี้ Python executor สร้าง Hyperframes project ต่อ job แล้วเรียก `npx hyperframes render` สำเร็จจริงกับ fixture แนวตั้งและแนวนอน

Definition of done:

- render sample composition เป็น MP4 ได้สำเร็จ

Validation:

- smoke render ผ่านบน local environment

### HF-02-02: Build render executor

- [x] สร้าง executor ที่รับ normalized render spec
- [x] map assets เข้าสู่ Hyperframes composition input
- [x] export output ไป storage

Status note:

- default executor ปัจจุบันเป็น `HyperframesCliRenderExecutor`; mock executor ยังถูกเก็บไว้สำหรับ narrow unit tests และ debug fallback เท่านั้น

Definition of done:

- worker รับ spec แล้ว render ได้จริง

Validation:

- output path ถูกสร้างและ status ถูก update

### HF-02-03: Add render worker loop

- [x] สร้าง worker ที่ดึง job จาก queue หรือ polling store
- [x] update status จาก `queued` -> `rendering` -> `completed|failed`
- [x] รองรับ graceful failure

Definition of done:

- มี local background render path ที่ใช้งานได้

Validation:

- สร้าง job แล้ว worker ประมวลผลจนจบได้

### HF-02-04: Add asset validation before render

- [x] ตรวจว่าไฟล์ asset เข้าถึงได้ก่อน render
- [x] validate subtitle parse ได้ก่อน compose
- [ ] validate intro/outro compatibility เบื้องต้น

Definition of done:

- งาน invalid ถูก fail ก่อนถึง render stage

Validation:

- malformed subtitle และ missing logo path ถูก reject อย่างถูกต้อง

### HF-02-05: Export debug artifacts

- [x] เก็บ normalized render spec เป็น artifact
- [x] เก็บ render log summary
- [ ] พิจารณา artifact สำหรับ preview metadata หรือ composition trace

Definition of done:

- debug artifact ดึงออกมาดูได้จาก API หรือ storage

Validation:

- มี artifact อย่างน้อย `normalized_render_spec.json`

## Phase HF-03: Template Routing + Templates

### HF-03-01: Implement orientation detection

- [x] อ่าน width, height, rotation จาก metadata
- [x] normalize rotation ก่อนคำนวณ orientation
- [x] สรุป result เป็น `vertical`, `horizontal`, หรือ `manual_required`

Definition of done:

- วิดีโอแนวตั้งและแนวนอนถูก classify ได้ถูกต้องใน fixture หลัก

Validation:

- มี tests สำหรับ rotated video และ square input

### HF-03-02: Implement template router

- [x] route จาก detected orientation ไปยัง template family
- [x] รองรับ user override
- [x] ป้องกัน invalid override combinations

Definition of done:

- router คืนค่า family และ variant ได้แน่นอน

Validation:

- tests ครอบคลุม `auto`, forced `vertical`, forced `horizontal`

### HF-03-03: Build Vertical Input Template V1

- [x] สร้าง Hyperframes composition สำหรับ vertical clips
- [x] วาง main video เต็ม frame
- [x] วาง logo slot, subtitle safe zone, basic motion tokens
- [x] รองรับ intro/outro insertion เบื้องต้นใน timeline

Status note:

- generated Hyperframes composition path render vertical output ได้จริงแล้ว; อย่างไรก็ตาม TS template descriptor/scaffold ยังไม่ใช่ source of truth หลักของ render path

Definition of done:

- vertical input render ออกมาโดย layout ไม่เพี้ยน

Validation:

- render sample 9:16 fixture ผ่าน

### HF-03-04: Build Horizontal Input Template V1

- [x] สร้าง Hyperframes composition สำหรับ horizontal clips
- [x] ออกแบบ layout เช่น framed video + background
- [x] กำหนด logo placement และ subtitle safe zone แยกจาก vertical
- [x] ตรวจว่าเนื้อหาหลักไม่ถูก crop ผิดบริบท

Status note:

- current render path ใช้ framed main video + blurred background สำหรับ horizontal family และผ่าน smoke render จริงแล้ว; งาน polish เชิง visual ยังทำได้ต่อ

Definition of done:

- horizontal input render ผ่าน template เฉพาะได้

Validation:

- render sample 16:9 fixture ผ่าน

### HF-03-05: Implement subtitle layer behavior

- [ ] รองรับ word-by-word highlight จาก JSON word-level timing
- [x] ทำ fallback phrase-level mode เมื่อ timing ไม่ละเอียดพอ
- [x] แยก typography/theme token ต่อ template

Definition of done:

- subtitle sync ได้กับ sample inputs หลัก

Validation:

- tests ครอบคลุม word-level และ fallback modes

### HF-03-06: Implement branding layer behavior

- [x] รองรับ PNG/SVG logo
- [x] กำหนด position, opacity, z-index ผ่าน theme tokens
- [x] แยก placement preset ต่อ template family

Status note:

- logo path ถูกพิสูจน์แล้วใน real smoke render ระดับ service executor; งานที่เหลือคือ visual polish และ coverage เพิ่มในหลาย family/placement presets

Definition of done:

- logo แสดงผลถูกต้องใน vertical และ horizontal templates

Validation:

- visual smoke check ผ่านทั้งสอง family

### HF-03-07: Implement intro/outro sequencing

- [x] เพิ่ม intro scene ก่อน main video
- [x] เพิ่ม outro scene หลัง main video
- [ ] รองรับ transition พื้นฐาน เช่น cut/fade
- [x] คำนวณ timing ตาม duration จริงของ source video

Status note:

- runtime path ต่อ intro/main/outro ตาม media duration จริงแล้ว แต่ยังไม่มี transition layer และยังไม่มี smoke test เฉพาะกรณี intro/outro เปิดใช้งาน

Definition of done:

- timeline ทำงานกับ duration แปรผันได้

Validation:

- sample clip สั้นและยาวต่างกัน render ถูกลำดับ

## Phase HF-04: Frontend Studio V1

### HF-04-01: Create dedicated frontend route/page

- [x] สร้างหน้าใหม่แยกจาก upload flow เดิม
- [x] แยก branding/UI language ของ service นี้ออกจาก orchestrator dashboard เดิม
- [x] มี entry สำหรับ upload source video และ optional assets

Definition of done:

- ผู้ใช้เข้าหน้าใหม่และสร้าง job ได้โดยไม่ยุ่งกับ flow เดิม

Validation:

- manual flow upload -> create job ทำงานครบ

### HF-04-02: Implement upload form and config UI

- [x] รองรับ source video, intro, outro, logo, subtitle
- [x] รองรับเลือก `auto`, `vertical`, `horizontal`
- [x] รองรับ subtitle theme / brand theme ขั้นต้น

Definition of done:

- form ส่งข้อมูลได้ครบตาม API contract

Validation:

- network payload ตรงตาม schema

### HF-04-03: Implement status screen

- [x] poll job status
- [x] แสดง progress, detected orientation, selected template, error summary
- [x] แสดงลิงก์ download เมื่อ completed

Definition of done:

- ผู้ใช้ติดตาม job lifecycle ได้ตั้งแต่สร้างงานจนจบ

Validation:

- status เปลี่ยนหน้า UI ตาม backend state จริง

### HF-04-04: Add artifact/debug view

- [x] แสดง normalized render spec หรือ debug artifact ที่จำเป็น
- [ ] จำกัด artifact view เฉพาะ dev/debug mode หากจำเป็น

Definition of done:

- ทีม dev ใช้หน้าจอนี้ debug job ได้เร็วขึ้น

Validation:

- artifact อย่างน้อย 1 ชิ้นอ่านได้จาก UI

## Phase HF-05: Validation, Fixtures, Hardening

### HF-05-01: Create video fixtures

- [ ] เตรียม vertical fixture
- [ ] เตรียม horizontal fixture
- [ ] เตรียม subtitle JSON fixture
- [ ] เตรียม logo fixture และ intro/outro fixture สั้น

Status note:

- ตอนนี้ tests ใช้ byte fixtures inline; ยังไม่มี fixture media files แยกใช้งานซ้ำ

Definition of done:

- test suite มี fixture พอสำหรับ smoke tests หลัก

Validation:

- fixtures ใช้ซ้ำได้ใน local tests

### HF-05-02: Add API validation tests

- [x] test create-job success
- [ ] test missing source video
- [ ] test invalid subtitle format
- [ ] test invalid template override

Definition of done:

- API validation ครอบคลุม failure cases สำคัญ

Validation:

- test suite ผ่านต่อเนื่อง

### HF-05-03: Add template router tests

- [ ] test vertical detection
- [ ] test horizontal detection
- [ ] test rotation normalization
- [x] test square/manual fallback

Status note:

- มี tests สำหรับ `resolve_template_family` และ manual fallback แล้ว แต่ detection path ที่พึ่ง ffprobe ยังไม่ถูกตรึงด้วย fixture tests

Definition of done:

- routing logic ถูกตรึงด้วย tests

Validation:

- มี test fixtures ครอบคลุม edge cases หลัก

### HF-05-04: Add render smoke tests

- [x] render vertical job เต็ม flow
- [x] render horizontal job เต็ม flow
- [x] render subtitle-enabled job
- [x] render intro/outro-enabled job

Status note:

- ตอนนี้มี automated smoke test ผ่าน `HyperframesCliRenderExecutor` สำหรับ vertical/horizontal base flow และ horizontal flow ที่เปิด subtitle + logo + intro/outro จริงแล้ว

Definition of done:

- pipeline ของ service ใหม่ผ่าน smoke tests อย่างน้อย 4 แบบ

Validation:

- output files ถูกสร้างจริงและ playable

### HF-05-05: Add operational limits and cleanup policy

- [ ] กำหนด max video duration สำหรับ V1
- [ ] กำหนด max upload size
- [ ] กำหนด render timeout
- [ ] กำหนด asset/output retention policy

Definition of done:

- service มี guardrails ขั้นต่ำสำหรับ local/prototype deployment

Validation:

- invalid oversized input ถูก reject ตาม policy

### HF-05-06: Prepare developer runbook

- [x] เพิ่มคำสั่ง run API service
- [x] เพิ่มคำสั่ง run worker
- [x] เพิ่มคำสั่ง run frontend route สำหรับ local dev
- [x] เพิ่มคำสั่ง test/smoke render

Definition of done:

- dev ใหม่ในทีมรันระบบนี้ locally ได้จากเอกสาร

Validation:

- ลองตาม runbook แล้วระบบขึ้นได้จริง

## Milestone Plan

## Milestone M1: Render Skeleton

เป้าหมาย:

- create job API
- status API
- worker render skeleton
- minimal Hyperframes render สำเร็จ

Required tasks:

- HF-00-01
- HF-00-02
- HF-00-03
- HF-00-04
- HF-01-01
- HF-01-02
- HF-01-04
- HF-01-05
- HF-02-01
- HF-02-02
- HF-02-03

## Milestone M2: Template-Based Rendering

เป้าหมาย:

- orientation detection
- template router
- vertical/horizontal templates render ได้จริง
- logo + subtitle ทำงานได้

Required tasks:

- HF-03-01
- HF-03-02
- HF-03-03
- HF-03-04
- HF-03-05
- HF-03-06

## Milestone M3: End-to-End Studio V1

เป้าหมาย:

- หน้า frontend แยก
- upload/configure/status/download flow ครบ
- intro/outro sequencing ใช้งานได้

Required tasks:

- HF-01-03
- HF-03-07
- HF-04-01
- HF-04-02
- HF-04-03
- HF-04-04

## Milestone M4: Hardening

เป้าหมาย:

- fixtures
- smoke tests
- operational limits
- runbook

Required tasks:

- HF-05-01
- HF-05-02
- HF-05-03
- HF-05-04
- HF-05-05
- HF-05-06

## Ready-Now Tasks

- [x] HF-00-01: Create service folder skeleton
- [x] HF-00-02: Define service boundary and runtime split
- [x] HF-00-03: Freeze V1 request/response contract
- [x] HF-00-04: Define normalized render spec
- [x] HF-00-05: Define subtitle JSON schema

## Recommended Next Tasks

- [ ] HF-00-05: wire subtitle typed schema เดียวกันเข้ากับ frontend types และ upload validation
- [ ] HF-02-04: add intro/outro compatibility validation ก่อน render
- [ ] HF-03-05: implement word-by-word subtitle highlight บน real render path
- [ ] HF-05-01: add reusable fixture media files
- [ ] HF-05-03: add orientation detection tests with ffprobe-backed fixtures

## Risks

- Hyperframes runtime integration อาจต้องใช้ Node execution path เพิ่ม ทำให้ deployment ซับซ้อนขึ้น
- งาน render video มีต้นทุนเครื่องสูงกว่างาน API ปกติ
- subtitle JSON ถ้าไม่ล็อก schema ตั้งแต่ต้น จะทำให้ frontend/backend/render layer ตีความไม่ตรงกัน
- horizontal template ถ้า design ไม่ดี จะทำให้ output ดูไม่ premium แม้ technically render ถูก
- intro/outro timing และ subtitle timing อาจมี edge case เมื่อ asset duration ไม่สอดคล้องกัน

## Open Decisions

- จะวาง Hyperframes runtime ภายใน service เดียว หรือแยก render microservice อีกชั้น
- จะใช้ queue อะไรใน local/dev/prod-like flow
- จะเก็บ job metadata ที่ไหนใน V1
- frontend หน้าใหม่จะอยู่ใต้ `frontend/` เดิมหรือแยกแอปในภายหลัง
- จะรองรับ preview image/thumbnail ใน V1 หรือไม่

## Definition Of V1 Done

V1 ถือว่าเสร็จเมื่อมีครบทั้งหมด:

- ผู้ใช้อัปโหลด source video และ optional assets ได้จากหน้าใหม่
- ระบบสร้าง job และรายงานสถานะได้
- ระบบ detect orientation และ route ไป template family ที่ถูกต้อง หรือให้ผู้ใช้ override ได้
- vertical input และ horizontal input render ผ่าน template แยกกันได้จริง
- output MP4 ดาวน์โหลดได้
- logo และ subtitle JSON ทำงานได้
- มี smoke tests ขั้นต่ำและ runbook สำหรับทีม