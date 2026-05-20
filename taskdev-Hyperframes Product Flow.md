# Hyperframes Product Flow - Development Tasks

## Objective

เอกสารนี้แตกงานจาก [docs/Hyperframes Product Flow.md](./docs/Hyperframes%20Product%20Flow.md) ให้อยู่ในรูป task development plan ที่ทีมสามารถใช้ลงมือพัฒนาได้จริงสำหรับการเปลี่ยนระบบ Hyperframes จาก **job-first flow** ไปเป็น **project-first flow** โดยใช้ Hyperframes Studio ร่วมกับ Smart Cut Reel อย่างมีบทบาทชัดเจน

เป้าหมายหลัก:

- เปลี่ยน product model จาก `upload -> create job -> render` เป็น `project -> revision -> render job`
- ใช้ Smart Cut Reel เป็น workflow/orchestration layer
- ใช้ Hyperframes Studio เป็น editing/preview layer
- ลดความซ้ำซ้อนของ editor functionality ใน frontend ปัจจุบัน
- ทำให้ preview, revision, และ render ผูกกับ workspace เดียวกันในระยะถัดไป

## Scope Summary

### In Scope

- เพิ่ม domain model ใหม่สำหรับ `project`, `revision`, `render job`
- ออกแบบและ implement frontend flow ใหม่: new project, project detail, studio, render history
- สร้าง backend/project storage layer สำหรับ Hyperframes workspace
- ทำให้ upload flow ปัจจุบันกลายเป็น `project setup` แทน `create render job` โดยตรง
- เชื่อม Hyperframes Studio ให้มีบทบาทใน product flow อย่างชัดเจน
- รองรับ render จาก revision snapshot

### Out Of Scope

- collaborative editing หลาย user พร้อมกัน
- comment threads / approval workflow เต็มรูปแบบ
- permissions model แบบละเอียด owner/editor/viewer
- production-grade remote Hyperframes Studio hosting
- template marketplace และ preset management UI เต็มรูปแบบ

## Working Assumptions

- backend หลักของ repo ยังใช้ Python เป็น orchestration core
- Hyperframes Studio ณ ตอนนี้ยังทำงานผ่าน preview server/workspace แยกได้เร็วที่สุด
- render pipeline ปัจจุบันยังอิง `job + normalized render spec` และต้อง migrate อย่างค่อยเป็นค่อยไป
- upload flow และ job dashboard ปัจจุบันยัง usable อยู่ และควรถูก refactor ต่อ ไม่ต้องทิ้งทั้งหมด
- phase แรกควรแยก UX และ data model ก่อน แล้วค่อยเชื่อม shared workspace แบบเต็ม

## Current Status Snapshot

สถานะ ณ ตอนนี้อิงจาก implementation ใน repo:

- Done: standalone Hyperframes service, job API, render worker, output/artifact flow, frontend upload form, job dashboard, embedded Hyperframes Studio shell, local studio workspace และ preview server path
- Done: backend render path รองรับ logo-generated intro และ render จริงผ่าน Hyperframes CLI
- Done: มีเอกสาร product flow แยกแล้ว
- Done: project domain model, revision model, project storage/revision storage, initial project APIs, project workspace scaffold, และ initial frontend project-first pages ถูก implement แล้ว
- Done: browser-validated flow สำหรับ create project ผ่าน Next proxy -> redirect/open project detail ใช้งานได้จริงใน local dev
- Done: draft render จาก project detail สร้าง job ที่ trace กลับไป `project_id` และ `revision_id` ได้ และ render history แสดงบน project detail แล้ว
- Partial: หน้า `/hyperframes` ถูกปรับเป็น full-width workspace entry + template catalog แล้ว และ preset selection ถูกเชื่อมไปยัง project setup จริง, แต่ยังคงมี legacy direct render path อยู่ด้านล่าง, ตอนนี้มี project-specific studio route แล้ว แต่ preview server ใต้ iframe ยังเป็น shared workspace, revision save/named revision ยังไม่เชื่อมกับ Studio จริง
- Pending: shared workspace lifecycle แบบ bind ต่อ project/revision จริง, named revision workflow, render final path, migration path จาก create-job form ปัจจุบัน

## Suggested Delivery Phases

### Phase PF-00: Product and Domain Foundations

เป้าหมาย: แช่แข็ง product model ใหม่และ data contracts ให้ทีมพัฒนาได้ตรงกัน

### Phase PF-01: Backend Project Domain

เป้าหมาย: สร้าง backend abstraction สำหรับ project, revision, workspace และความสัมพันธ์กับ render job

### Phase PF-02: Frontend IA and Routing Refactor

เป้าหมาย: แยกหน้า `new project`, `project detail`, `studio`, `jobs` ออกจากกันอย่างชัดเจน

### Phase PF-03: Workspace and Studio Integration

เป้าหมาย: ทำให้ Studio เปิดและแก้ไข workspace ที่เป็น source of truth ของ project revision

### Phase PF-04: Render from Revision

เป้าหมาย: ให้ render ทุกครั้งอิง revision snapshot แทน asset form โดยตรง

### Phase PF-05: Migration, Hardening, and Cleanup

เป้าหมาย: ย้าย flow เดิม, ลด UI/functionality ที่ซ้ำซ้อน, เพิ่ม test coverage และ hardening

## Dependency Map

- PF-00 ต้องเสร็จก่อน PF-01 และ PF-02
- PF-01 ต้องเสร็จขั้นต่ำก่อน PF-03 และ PF-04
- PF-02 เดินคู่กับ PF-01 ได้บางส่วนหลัง route/data contract ชัด
- PF-03 ขึ้นกับ PF-01 และบางส่วนของ PF-02
- PF-04 ขึ้นกับ PF-01 และ PF-03
- PF-05 ทำหลัง PF-02, PF-03, PF-04 เริ่มใช้งานได้จริง

## Detailed Tasks

## Phase PF-00: Product and Domain Foundations

### PF-00-01: Freeze project-first domain model

- [x] กำหนด schema ของ `project`
- [x] กำหนด schema ของ `revision`
- [ ] กำหนด schema ของ `render job` ที่อ้างกลับไป `revision_id`
- [x] สรุปความสัมพันธ์ระหว่าง `project -> revisions -> render jobs`

Definition of done:

- ทีม backend/frontend อ้าง model ชุดเดียวกันได้
- มี field list ขั้นต่ำสำหรับ V1.5 migration

Validation:

- มีตัวอย่าง object จริงอย่างน้อย 1 project ที่มี 2 revisions และ 2 render jobs

### PF-00-02: Freeze route and screen map

- [x] สรุป route ใหม่ที่ต้องมี เช่น `/hyperframes/new`, `/hyperframes/projects/[projectId]`, `/hyperframes/projects/[projectId]/studio`, `/hyperframes/jobs/[jobId]`
- [x] ระบุว่า route เดิม `/hyperframes` จะทำหน้าที่อะไรในช่วง transition
- [x] กำหนด redirect behavior หลัง create project

Definition of done:

- ไม่มี ambiguity ว่าหน้าไหนคือ setup, studio, review, jobs

Validation:

- route map review แล้วอธิบาย end-to-end flow ได้ใน 1 ลำดับโดยไม่ย้อนกันเอง

### PF-00-03: Freeze phase-1 migration strategy

- [x] สรุปว่าจะ migrate แบบ parallel flow หรือ replace flow
- [x] กำหนดว่าฟอร์ม upload เดิมจะถูก reuse เป็น `Project Setup` หรือ split ออกบางส่วน
- [x] กำหนด compatibility strategy กับ job API ปัจจุบัน

Definition of done:

- ทีมรู้ว่า code path ไหนเป็น legacy transitional path และ path ไหนเป็น target path

Validation:

- migration note ระบุได้ว่าผู้ใช้ปัจจุบันจะยังใช้งาน flow เดิมได้หรือไม่

### PF-00-04: Define project workspace contract

- [x] กำหนดโครงสร้าง workspace ต่อ project/revision
- [x] ระบุไฟล์ขั้นต่ำ เช่น `index.html`, `assets/`, `compositions/`, `hyperframes.json`, manifest metadata
- [x] สรุป naming convention และ path policy

Definition of done:

- backend และ studio integration ใช้ workspace contract เดียวกัน

Validation:

- สร้างตัวอย่าง workspace tree ของ project หนึ่งชิ้นได้ครบ

## Phase PF-01: Backend Project Domain

### PF-01-01: Implement project storage abstraction

- [x] สร้าง storage abstraction สำหรับ `project` metadata
- [ ] รองรับ create/read/list/update ขั้นต้น
- [x] รองรับ local filesystem mode สำหรับ dev

Definition of done:

- สร้าง project ใหม่ได้โดยไม่ต้องสร้าง render job ทันที

Validation:

- test create/read/list project ผ่าน

### PF-01-02: Implement revision storage abstraction

- [x] สร้าง abstraction สำหรับ revision metadata
- [x] รองรับ create draft revision
- [ ] รองรับ named revision
- [x] ผูก revision กับ project

Definition of done:

- project หนึ่งชิ้นมี revision หลายตัวได้

Validation:

- test create revision และ list revisions ต่อ project ผ่าน

### PF-01-03: Implement project workspace manager

- [x] สร้าง service สำหรับ scaffold workspace ต่อ project/revision
- [ ] รองรับ copy/clone revision workspace
- [ ] รองรับ rebuild workspace เมื่อไฟล์เสียหรือหาย

Definition of done:

- เมื่อสร้าง project แล้วมี workspace พร้อมใช้งานสำหรับ Studio ทันที

Validation:

- smoke check แล้ว workspace ที่สร้างใหม่เปิดผ่าน `hyperframes preview` ได้

### PF-01-04: Map render jobs to revisions

- [x] ขยาย render job model ให้มี `project_id` และ `revision_id`
- [x] เก็บ reference ย้อนกลับจาก output ไป revision ต้นทาง
- [ ] รองรับ render history ต่อ project และต่อ revision

Definition of done:

- render job ทุกตัว trace กลับไปยัง source revision ได้

Validation:

- test query render jobs by project/revision ผ่าน

### PF-01-05: Add project-level API surface

- [x] เพิ่ม API สำหรับ create project
- [x] เพิ่ม API สำหรับ project detail
- [x] เพิ่ม API สำหรับ list revisions
- [ ] เพิ่ม API สำหรับ create revision

Definition of done:

- frontend ใหม่สามารถทำงานแบบ project-first ได้โดยไม่ต้องอาศัย job endpoints อย่างเดียว

Validation:

- API contract tests ผ่านขั้นต่ำสำหรับ create/read project and revision

## Phase PF-02: Frontend IA and Routing Refactor

### PF-02-01: Create `New Project` page

- [x] สร้าง route ใหม่สำหรับ project setup
- [x] reuse logic จาก upload form เดิมเท่าที่เหมาะสม
- [x] เปลี่ยน submit behavior จาก `create render job` เป็น `create project`

Implementation note:

- root route `/hyperframes` now acts as the template catalog / workspace entry page and deep-links into `/hyperframes/new?preset=...` for preset-based workspace creation

Definition of done:

- ผู้ใช้สร้าง project ได้และถูกพาไป project overview แทน job page

Validation:

- browser flow: upload สำเร็จ -> redirect ไป project detail

### PF-02-02: Create `Project Detail` page

- [x] แสดง project header
- [x] แสดง source summary และ assets
- [x] แสดง active revision
- [x] แสดง render history
- [x] เพิ่ม CTA: open in studio, render draft, render final

Definition of done:

- project detail เป็นหน้ากลางที่ใช้ควบคุม flow ได้จริง

Validation:

- browser flow: create project -> project detail -> open in studio or render draft

### PF-02-03: Move current upload form into setup role

- [ ] เปลี่ยน copy/label ของ form ให้ชัดว่าเป็น setup/intake ไม่ใช่ studio
- [ ] ย้าย field ที่ควรอยู่ใน setup เท่านั้นให้อยู่หน้านี้
- [ ] ระบุ field ที่ควรถูกย้ายไป preset/studio ในอนาคต

Definition of done:

- ไม่มี UX ambiguity ว่าฟอร์มนี้คือ editor

Validation:

- UX copy review แล้วแยก `setup` กับ `studio` ชัดเจน

### PF-02-04: Keep job detail page as render status view

- [ ] ปรับ job detail page ให้ link กลับไป project/revision ได้
- [ ] แสดง source revision ของ output
- [ ] เพิ่ม CTA กลับไป project detail และ studio

Definition of done:

- job page ทำหน้าที่ review/status ชัดเจน ไม่ทำหน้าที่ setup/edit

Validation:

- browser flow จาก job page กลับไป project detail ได้

### PF-02-05: Introduce project navigation shell

- [x] เพิ่ม navigation หรือ breadcrumb สำหรับ project-first flow
- [x] แสดง current context เช่น project name / revision / latest render
- [x] ใช้ shell เดียวกันใน project detail และ studio page ระดับแรก

Definition of done:

- product IA ดูเป็นระบบเดียว ไม่ใช่หน้ากระจัดกระจาย

Validation:

- clickthrough ระหว่าง new project, project detail, studio, jobs ไม่หลงทาง

## Phase PF-03: Workspace and Studio Integration

### PF-03-01: Create studio launch strategy per project

- [x] ระบุว่า Studio จะเปิดผ่าน iframe, new tab, หรือ dedicated page เป็นหลัก
- [ ] กำหนดว่าแต่ละ project/revision จะ map ไป preview workspace อย่างไร
- [x] กำหนด URL convention สำหรับเปิด Studio ของ project นั้น

Definition of done:

- ผู้ใช้เปิด Studio ของ project ที่ถูกต้องได้ทุกครั้ง

Validation:

- open in studio จาก project detail แล้วเห็น workspace ตรงกับ revision ปัจจุบัน

### PF-03-02: Bind Studio to project workspace

- [ ] เปลี่ยน embedded studio shell จาก static workspace ให้ผูกกับ project/revision จริง
- [ ] รองรับ load current revision workspace
- [ ] รองรับ refresh/reopen studio หลัง save revision

Definition of done:

- Studio ไม่ใช่ demo shell แล้ว แต่เป็น editor ของ project จริง

Validation:

- project A และ project B เปิด Studio แล้วไม่ชน workspace กัน

### PF-03-03: Implement save draft from Studio workspace

- [ ] เพิ่ม workflow save draft revision จาก state ของ workspace
- [ ] persist metadata เช่น updated_at, created_by, note
- [ ] ทำให้ project detail เห็น revision ล่าสุดทันที

Definition of done:

- มี revision draft ที่สะท้อนงานที่แก้ใน Studio จริง

Validation:

- edit in studio -> save draft -> project detail shows updated revision

### PF-03-04: Implement named revision creation

- [ ] เพิ่ม action สำหรับ save named revision
- [ ] clone workspace state ไป revision ใหม่
- [ ] เก็บ revision note/label

Definition of done:

- ผู้ใช้สร้าง milestone revision ได้โดยไม่ทับ draft เดิม

Validation:

- create named revision แล้ว revision list แสดงทั้ง draft และ named revision

### PF-03-05: Add studio availability and recovery UX

- [ ] แสดงสถานะว่า studio server/workspace พร้อมหรือไม่
- [ ] เพิ่ม CTA เช่น start studio, rebuild workspace, reopen studio
- [ ] handle error state หาก preview server unavailable

Definition of done:

- ผู้ใช้ไม่เจอ blank embed แบบไม่มีคำอธิบาย

Validation:

- ปิด studio server แล้ว UI แสดง recovery action ที่ชัดเจน

## Phase PF-04: Render from Revision

### PF-04-01: Implement render-draft from project detail

- [x] เพิ่ม action `Render Draft` บน project detail
- [x] ให้ backend สร้าง render job จาก active revision
- [x] ส่งผู้ใช้ไป job page หรือ render panel ตาม UX ที่ตกลง

Definition of done:

- ผู้ใช้ render ได้โดยไม่ต้องอัปโหลด asset ใหม่ทุกครั้ง

Validation:

- render draft จาก project detail แล้ว job completed สำเร็จ

### PF-04-02: Implement render-final from revision

- [ ] เพิ่ม action `Render Final`
- [ ] แยก render mode และ config จาก draft
- [ ] เก็บ metadata ว่า output นี้เป็น final candidate หรือ final export

Definition of done:

- draft และ final มี mode ชัดเจนใน job history

Validation:

- project เดียวกันสร้างได้ทั้ง draft job และ final job

### PF-04-03: Snapshot revision before render

- [ ] ทำ snapshot/freeze revision state ก่อนยิง render ทุกครั้ง
- [ ] ป้องกันไม่ให้ workspace edit ขณะ render ทำให้ output ไม่ deterministic
- [ ] เก็บ reference ของ snapshot path/hash

Definition of done:

- output trace กลับไป source snapshot ที่แน่นอนได้

Validation:

- render log แสดง revision snapshot identifier

### PF-04-04: Show render history on project detail

- [ ] แสดง latest jobs ต่อ project
- [ ] แสดง source revision ของแต่ละ job
- [ ] รองรับ quick open output และ quick open job detail

Definition of done:

- project detail เป็นศูนย์กลางของ iteration history

Validation:

- browser view เห็น render history และเปิด output/job ได้จากหน้าเดียว

### PF-04-05: Keep backward compatibility with direct job creation during migration

- [ ] กำหนดว่า direct create-job path จะยังอยู่หรือไม่ในช่วง migration
- [ ] ถ้ายังอยู่ ให้ map ไป temporary project/revision อัตโนมัติหรือ mark เป็น legacy job
- [ ] ระบุ deprecation plan ชัดเจน

Definition of done:

- migration ไม่ทำให้ flow เดิมเสียแบบหักดิบ

Validation:

- legacy path ทำงานได้หรือถูก redirect อย่างชัดเจน

## Phase PF-05: Migration, Hardening, and Cleanup

### PF-05-01: Remove duplicate language and UI positioning

- [ ] ลดการใช้คำว่า `studio` ในหน้าที่เป็น setup/intake
- [ ] rename sections ให้สะท้อน role จริง เช่น setup, edit, render, review
- [ ] ปรับ copy ทั้ง flow ให้ consistent

Definition of done:

- product language ไม่ทำให้ผู้ใช้สับสนว่าหน้าไหนมีหน้าที่อะไร

Validation:

- content review ผ่านโดยอธิบาย flow ได้ชัดใน 4 stages: setup/edit/render/review

### PF-05-02: Audit redundant features against Hyperframes Studio

- [ ] ตรวจสอบ feature ฝั่ง frontend ที่อาจซ้ำกับ studio ในอนาคต
- [ ] freeze ว่าอะไรจะไม่ทำเอง เช่น timeline editor, preview editor, source editor
- [ ] บันทึก architectural decision ไว้ใน docs

Definition of done:

- มี decision ที่ช่วยกัน scope creep และซ้ำซ้อนในอนาคต

Validation:

- design review แล้วไม่มี roadmap item ฝั่ง frontend ที่ชนกับ Studio ตรงๆ โดยไม่จำเป็น

### PF-05-03: Add end-to-end tests for project-first flow

- [ ] test create project
- [ ] test open studio path
- [ ] test save revision
- [ ] test render draft/final from revision
- [ ] test project detail render history

Definition of done:

- flow ใหม่มี regression coverage ขั้นต้น

Validation:

- automated tests หรือ scripted smoke flows ผ่านใน local dev

### PF-05-04: Add operational runbook for Studio + project workspace flow

- [ ] อธิบายวิธี start backend, frontend, studio preview
- [ ] อธิบายวิธี create project และ open studio
- [ ] อธิบายวิธี recover หาก workspace/studio เสีย

Definition of done:

- developer ใหม่เปิดระบบและ debug flow ได้โดยไม่ต้องถามทีมปากเปล่า

Validation:

- ทำตาม runbook จากเครื่องใหม่หรือ shell ใหม่แล้ว flow ขึ้นได้จริง

### PF-05-05: Review PRD alignment and update status docs

- [ ] sync task status กับเอกสาร product flow และ PRD หลัก
- [ ] อัปเดต phase status เมื่อ implementation แต่ละช่วงเสร็จ
- [ ] รักษา task doc ให้เป็น source of truth ของ rollout นี้

Definition of done:

- ทีมใช้เอกสารนี้ติดตามงานต่อได้โดยไม่แตกหลายแหล่ง

Validation:

- เอกสาร task, PRD, และ product flow ไม่ขัดกันในประเด็นหลัก

## Suggested First Execution Slice

เพื่อเริ่มงานโดยเร็วโดยไม่รื้อทั้งหมดในครั้งเดียว แนะนำลำดับ implementation แรกดังนี้:

1. ทำ PF-00-01 ถึง PF-00-04 ให้ model และ route ชัด
2. ทำ PF-01-01 ถึง PF-01-03 สำหรับ project/revision/workspace storage
3. ทำ PF-02-01 และ PF-02-02 เพื่อให้เกิด `New Project` และ `Project Detail`
4. ทำ PF-04-01 เพื่อให้ render draft จาก project detail ได้ก่อน
5. ค่อยทำ PF-03-02 ถึง PF-03-04 เพื่อ bind Studio เข้ากับ revision จริง

## Exit Criteria for First Milestone

Milestone แรกถือว่าสำเร็จเมื่อ:

- ผู้ใช้สร้าง project ใหม่ได้
- ระบบสร้าง revision แรกให้อัตโนมัติได้
- ผู้ใช้เข้า project detail ได้
- ผู้ใช้ render draft จาก project detail ได้โดยไม่ต้องอัปโหลดใหม่
- render job trace กลับไป source revision ได้
- Hyperframes Studio เปิดจาก project context ได้อย่างน้อยในระดับ workspace per project

## Notes

- ระยะแรกสามารถใช้ studio preview server แบบ local/dev-first ไปก่อน แล้วค่อย harden ในระยะถัดไป
- งานส่วนที่เกี่ยวกับ collaboration และ approval ควรถูกเลื่อนไปหลังจาก project-first + revision-first flow เสถียรก่อน
- หากต้องตัด scope ให้เร็วที่สุด ให้ prioritise project model, project detail page, render-from-revision, และ studio launch path ก่อน named revision และ advanced history UI