# Product Requirements Document (PRD)
**Project Name:** Automated Video Finishing Service
**Engine/Framework:** Hyperframes (HTML-to-Video)
**Document Date:** May 18, 2026

## 1. Project Overview
ระบบอัตโนมัติสำหรับการตกแต่งและประกอบวิดีโอขั้นสุดท้าย (Finishing / Post-processing) โดยพัฒนาเป็น **Service แยกจาก pipeline หลักของ Smart Cut Reel** ในระยะแรก เพื่อให้ทีมสามารถพัฒนาและทดลองฟีเจอร์ด้านงานภาพ, แบรนดิ้ง, และซับไตเติลได้เร็ว โดยไม่เพิ่มความซับซ้อนให้ orchestrator และ pipeline เดิม

Service นี้จะรับไฟล์วิดีโอหลักที่ผู้ใช้อัปโหลดเข้ามาโดยตรง และประกอบองค์ประกอบต่างๆ เช่น Intro/Outro, Branding Overlay และ Auto-Kinetic Subtitles ผ่าน Hyperframes จากนั้นเรนเดอร์เป็นไฟล์ MP4 พร้อมใช้งาน

ระบบต้องรองรับวิดีโอ input สองประเภทตั้งแต่ต้น:

*   **Vertical Input Template** สำหรับคลิปแนวตั้ง เช่น 9:16 หรือคลิปที่มี framing พร้อมใช้งานแล้ว
*   **Horizontal Input Template** สำหรับคลิปแนวนอน เช่น 16:9 ที่ต้องจัด layout สำหรับงานแนวตั้งหรือวางใน composition คนละแบบ

แนวทางนี้ทำให้ทีมสามารถแยกพัฒนา Hyperframes composition layer ออกจาก media-processing pipeline ปัจจุบัน และค่อยพิจารณาการเชื่อมต่อกับ pipeline เดิมในระยะถัดไปเมื่อฟีเจอร์นิ่งแล้ว

## 1.1 Product Boundary
*   ระยะเริ่มต้น **ไม่ผูกกับ pipeline เดิมโดยตรง**
*   ผู้ใช้จะอัปโหลดวิดีโอเข้ามายัง service นี้โดยตรง
*   Service นี้รับผิดชอบเฉพาะงาน finishing/composition/rendering
*   การดึง output หรือ artifact จาก pipeline เดิมจะเป็นงานในเฟสถัดไป ไม่ใช่เงื่อนไขของ V1

## 1.2 Delivery Model
*   พัฒนาเป็น **Standalone Hyperframes Service** แยกจาก orchestrator เดิม
*   มีหน้า frontend แยกสำหรับ upload, ตั้งค่า template, เลือก assets และสั่ง render
*   มี render worker หรือ backend execution path ของตัวเอง ไม่รันผ่าน pipeline เดิมใน V1

## 1.3 Input Modes

### A. Vertical Input Mode
สำหรับวิดีโอแนวตั้งที่พร้อมนำไปตกแต่งต่อได้ทันที เช่น คลิป 9:16 ที่ผ่านการ reframe มาแล้ว หรือคลิปที่ถ่ายเป็นแนวตั้งมาตั้งแต่ต้น

### B. Horizontal Input Mode
สำหรับวิดีโอแนวนอน เช่น 16:9 ที่ต้องใช้ template เฉพาะในการนำเสนอ เช่น วางวิดีโอใน frame แนวตั้ง, เติม background layer, หรือจัด subtitle/branding ให้เหมาะกับ composition ของคลิปแนวนอน

## 2. Core Features

### 2.1 Video Sequencing (ระบบต่อลำดับวิดีโออัตโนมัติ)
*   **Description:** ระบบสามารถนำไฟล์วิดีโอ Intro, Main Video และ Outro มาเรียงต่อกันเป็นไฟล์เดียวได้อย่างไร้รอยต่อ
*   **Requirements:**
    *   รองรับการกำหนด Timeline การเล่นคลิปผ่านโค้ด HTML/JS
    *   มี Transition พื้นฐานระหว่างรอยต่อคลิป เช่น Crossfade หรือ Cut ชน
    *   ระบบต้องรองรับความยาวของ Main Video แบบไดนามิก (ความยาวแต่ละคลิปไม่เท่ากัน) โดยให้ Outro เริ่มเล่นทันทีที่ Main Video จบ
    *   ใช้งานได้ทั้ง Vertical Input Template และ Horizontal Input Template

### 2.2 Automated Branding (ระบบประทับแบรนดิ้งและโลโก้)
*   **Description:** การสวม Overlay โลโก้หรือกราฟิกประจำแบรนด์ลงบนวิดีโอในตำแหน่งที่กำหนดไว้ตายตัว
*   **Requirements:**
    *   รองรับไฟล์ภาพแบบโปร่งใส (PNG, SVG)
    *   สามารถกำหนดตำแหน่ง (Positioning) ได้ผ่าน CSS เช่น มุมขวาบน (Top-right) หรือมุมขวาล่าง
    *   ปรับระดับความโปร่งแสง (Opacity) ของโลโก้ได้
    *   สามารถกำหนดเลเยอร์ (Z-index) ให้อยู่เหนือวิดีโอหลักเสมอ
    *   แต่ละ template ต้องมี branding placement preset ของตัวเอง เพื่อให้เหมาะกับ layout ของวิดีโอแนวตั้งและแนวนอน

### 2.3 Auto-Kinetic Subtitles (ระบบซับไตเติลเด้งตามเสียง)
*   **Description:** การแสดงผลข้อความซับไตเติลแบบไฮไลต์ทีละคำ (Word-by-word highlight) เพื่อดึงดูดความสนใจของผู้ชม
*   **Requirements:**
    *   รองรับการรับข้อมูลนำเข้าเป็นไฟล์ JSON/SRT ที่มี Timestamp ระดับคำ (Word-level timestamps)
    *   แสดงผลแอนิเมชันของตัวอักษร เช่น เด้งขยายตัว (Scale-up) หรือเปลี่ยนสีเมื่อถึงจังหวะเสียงพูด
    *   รองรับการตั้งค่าสไตล์ของกล่องข้อความ (Subtitle Box) ด้วยดีไซน์แนว Glassmorphism (Liquid Glass) เพื่อความพรีเมียมและอ่านง่าย
    *   แสดงผลซับไตเติลให้อยู่ในระยะปลอดภัย (Safe Zone) ของแพลตฟอร์มโซเชียลมีเดีย
    *   แต่ละ template ต้องมี subtitle safe-zone และ typography preset ของตัวเอง

### 2.4 Template Routing (ระบบเลือก Template อัตโนมัติ/กึ่งอัตโนมัติ)
*   **Description:** ระบบต้องสามารถเลือก Hyperframes template ให้ตรงกับชนิดของวิดีโอ input เพื่อให้ composition ถูกต้องตั้งแต่ต้น
*   **Requirements:**
    *   ตรวจสอบ orientation ของวิดีโอ input จาก metadata เช่น width/height
    *   route ไปยัง **Vertical Input Template** เมื่อไฟล์เป็นแนวตั้ง
    *   route ไปยัง **Horizontal Input Template** เมื่อไฟล์เป็นแนวนอน
    *   เปิดให้ผู้ใช้ override template ได้ในกรณีที่ต้องการเลือก layout เอง
    *   ระบบต้องแยก template implementation ออกจากกันอย่างชัดเจน เพื่อให้ปรับ motion, subtitle position, logo placement และ framing ได้อิสระ

## 3. Service Architecture Requirements

### 3.1 Standalone Service Boundary
*   Hyperframes finishing module ต้องถูกพัฒนาเป็น service ใหม่แยกจาก orchestrator หลัก
*   การ deploy, dependency และ queue/render execution ของ service นี้ต้องแยกจาก pipeline หลัก
*   หาก render ล้มเหลว ต้องไม่กระทบการทำงานของ pipeline เดิม

### 3.2 Input Contract
*   รองรับการอัปโหลด Main Video โดยตรง
*   รองรับ optional assets ได้แก่ Intro, Outro, Logo, Subtitle file
*   รองรับ input subtitle เป็น JSON ที่มี word-level timestamps เป็นหลัก
*   SRT รองรับได้เฉพาะกรณีที่ถูกแปลงหรือ enrich จนใช้งานกับ kinetic subtitle model ได้

### 3.3 Output Contract
*   ส่งออกไฟล์ MP4 (H.264) เป็นหลัก
*   เก็บ metadata ของ template ที่ใช้ในการ render ไว้ได้
*   ระบุได้ว่า output มาจาก Vertical Input Template หรือ Horizontal Input Template

### 3.4 V1 Scope
*   ทำงานแบบ standalone upload -> configure -> render -> download
*   ยังไม่เชื่อมกับ Smart Cut Reel pipeline เดิมโดยตรง
*   ยังไม่ทำ auto face-aware branding avoidance ใน V1
*   ยังไม่บังคับดึง transcript จาก pipeline เดิมใน V1

## 4. Acceptance Criteria
*   ระบบต้องทำงานเป็น service แยกจาก pipeline หลักได้จริง และสามารถรับไฟล์วิดีโอเข้าใช้งานได้โดยตรง
*   ระบบต้องตรวจจับหรือให้ผู้ใช้เลือกชนิด input ได้ถูกต้อง ระหว่าง Vertical Input Template และ Horizontal Input Template
*   วิดีโอแนวตั้งที่เข้ามาต้องถูก render ผ่าน template สำหรับแนวตั้งโดยไม่ทำให้ layout เพี้ยน
*   วิดีโอแนวนอนที่เข้ามาต้องถูก render ผ่าน template สำหรับแนวนอนโดยไม่ทำให้เนื้อหาหลักถูกตัดผิดบริบท
*   Intro, Main Video และ Outro ต้องต่อกันได้ตาม timeline ที่กำหนด และรองรับความยาวของ Main Video แบบไดนามิก
*   โลโก้ต้องแสดงผลในตำแหน่งที่กำหนดของแต่ละ template อย่างถูกต้องและไม่ถูก element อื่นทับ
*   ซับไตเติลต้อง sync กับ timestamp ที่รับเข้ามา และต้องอยู่ภายใน safe zone ของ template นั้น
*   ไฟล์ผลลัพธ์สุดท้ายต้องเป็น MP4 (H.264) ที่พร้อมอัปโหลดขึ้นโซเชียลมีเดีย

## 5. Recommended V1 Templates

### 5.1 Vertical Input Template
*   สำหรับคลิป 9:16 หรือคลิปแนวตั้งที่พร้อมใช้งาน
*   Subtitle วางบริเวณ lower-third สำหรับงาน short-form
*   Logo placement ใช้ตำแหน่งคงที่ที่เหมาะกับคลิปแนวตั้ง
*   Intro/Outro ใช้ motion ที่เน้น fill frame เต็มจอ

### 5.2 Horizontal Input Template
*   สำหรับคลิป 16:9 หรือคลิปแนวนอน
*   มี layout เฉพาะ เช่น main video card, blurred background, gradient background หรือ framed canvas
*   Subtitle และ branding ต้องวางตาม safe zone ของ composition ที่ต่างจาก vertical template
*   Template ต้องออกแบบให้รักษาเนื้อหาหลักของภาพแนวนอนโดยไม่บีบหรือ crop แบบผิดบริบท

## 6. Future Integration
*   ในเฟสถัดไป สามารถเพิ่มความสามารถ import output จาก Smart Cut Reel pipeline เดิมเข้ามาใช้เป็น Main Video ได้
*   สามารถรองรับ transcript/artifact จาก pipeline เดิมเป็น subtitle source ได้ในอนาคต
*   หาก service นี้นิ่งแล้ว ค่อยพิจารณาเชื่อมเข้ากับ orchestrator เป็น downstream finishing stage

## 7. Suggested Service Structure

Service นี้ควรถูกออกแบบเป็น Hyperframes-based rendering service ที่แยกหน้าที่ระหว่าง frontend, API layer, render orchestration และ composition templates ให้ชัดเจน เพื่อให้ template สำหรับวิดีโอแนวตั้งและแนวนอนพัฒนาแยกกันได้โดยไม่ชนกัน

### 7.1 High-Level Architecture
*   **Frontend Studio:** หน้าใช้งานสำหรับ upload วิดีโอ, เลือก template, อัปโหลด assets, ตั้งค่า subtitle/branding และสั่ง render
*   **Hyperframes API Service:** รับ request จาก frontend, validate input, สร้าง job, จัดเก็บ metadata และส่งงาน render ต่อ
*   **Render Worker:** ดึง job ไปประมวลผลด้วย Hyperframes composition และ export เป็น MP4
*   **Asset Storage:** เก็บ source video, intro/outro, logo, subtitle files และ rendered outputs
*   **Job Store / Metadata Store:** เก็บสถานะของงาน, template ที่เลือก, config ที่ใช้ และผลลัพธ์ของงาน render

### 7.2 Logical Component Split
*   **Upload Module:** รับไฟล์และจัดการ asset references
*   **Template Router:** ตรวจ orientation และ map ไปยัง Vertical Input Template หรือ Horizontal Input Template
*   **Composition Builder:** ประกอบ config ของ intro/outro, subtitle, branding, timing และ template slots ให้เป็น Hyperframes input model
*   **Render Executor:** เรียก Hyperframes render pipeline เพื่อสร้างไฟล์ output
*   **Job Status Module:** รายงานสถานะ queued, rendering, completed, failed
*   **Output Delivery Module:** ให้ frontend preview/download output ที่ render เสร็จแล้ว

### 7.3 Suggested Repository-Level Structure
โครงสร้างด้านล่างเป็นข้อเสนอเชิงเทคนิคสำหรับ service ใหม่ โดยเน้นให้ Hyperframes templates และ render logic แยกจาก business logic:

```text
services/
    hyperframes_finishing/
        api/
            routes/
                create_job.py
                get_job_status.py
                get_job_output.py
            schemas/
                job_request.py
                job_response.py
                template_config.py
        domain/
            job_service.py
            template_router.py
            composition_builder.py
            asset_manifest.py
        hyperframes/
            templates/
                vertical/
                    composition.ts
                    theme.ts
                    slots.ts
                horizontal/
                    composition.ts
                    theme.ts
                    slots.ts
            renderer/
                render_job.ts
                export_mp4.ts
                validate_assets.ts
        worker/
            run_render_job.py
            queue_consumer.py
        storage/
            object_store.py
            job_store.py
        tests/
            test_template_router.py
            test_job_api.py
            test_composition_builder.py
            test_render_flow.py
```

หมายเหตุ: ถ้าทีมต้องการแยก Node runtime สำหรับ Hyperframes ออกจาก Python API/worker ก็สามารถแยก `hyperframes/` เป็น service ย่อยอีกตัวได้ โดยให้ API service เรียกผ่าน internal HTTP หรือ queue job

## 8. Technical Design

### 8.1 Execution Model
V1 ควรใช้รูปแบบ asynchronous render job แทน synchronous request/response เนื่องจากงาน render วิดีโออาจใช้เวลาหลายวินาทีถึงหลายนาที และไม่เหมาะกับการรอผลใน request เดียว

**Recommended flow:**
1. ผู้ใช้อัปโหลดวิดีโอและ assets ผ่าน frontend studio
2. API service ตรวจสอบ input และสร้าง render job
3. ระบบบันทึก job status เป็น `queued`
4. Render worker ดึง job ไปประมวลผลด้วย Hyperframes
5. ระหว่าง render ระบบอัปเดตสถานะเป็น `rendering`
6. เมื่อสำเร็จ ระบบอัปเดตสถานะเป็น `completed` และเผย output URL
7. หากล้มเหลว ระบบอัปเดตสถานะเป็น `failed` พร้อม error summary

### 8.2 Orientation Detection and Template Routing
ระบบต้องตรวจสอบ orientation ของ input video จาก metadata เช่น `width`, `height`, `rotation` ก่อนเลือก template

**Routing rule เบื้องต้น:**
*   ถ้า display aspect ratio เป็นแนวตั้ง ให้ใช้ `vertical` template family
*   ถ้า display aspect ratio เป็นแนวนอน ให้ใช้ `horizontal` template family
*   ถ้า metadata มี rotation ต้อง normalize ก่อนตัดสิน orientation
*   ผู้ใช้สามารถ override template ได้จาก UI หากต้องการ

**V1 recommended behavior:**
*   `vertical` template family: รองรับ 9:16 และคลิปแนวตั้งใกล้เคียง
*   `horizontal` template family: รองรับ 16:9 และคลิปแนวนอนใกล้เคียง
*   square video ให้ถือเป็น manual choice ใน V1 เพื่อหลีกเลี่ยงการ route ผิด

### 8.3 Hyperframes Template Design
แต่ละ template ใน Hyperframes ควรมีชั้นย่อยที่แยกหน้าที่กัน เพื่อให้ maintenance ง่ายและปรับ style ได้เร็ว

**Per-template composition parts:**
*   **Scene Root:** canvas หลักและ frame timing ของ composition
*   **Background Layer:** gradient, blur background, image background หรือ color theme
*   **Main Video Layer:** พื้นที่วางวิดีโอหลักของ template นั้น
*   **Branding Layer:** โลโก้, watermark, badge หรือ sponsor mark
*   **Subtitle Layer:** กล่อง subtitle, word highlight animation และ safe-zone constraints
*   **Intro/Outro Layer:** scene สำหรับต้นคลิปและท้ายคลิป
*   **Transition Layer:** cut / fade / motion transitions ระหว่าง scene

### 8.4 Template Slot Contract
เพื่อให้ frontend และ backend คุยกันชัดเจน ควรกำหนด slot model กลางสำหรับทุก template

**Suggested slots:**
*   `main_video`
*   `intro_video`
*   `outro_video`
*   `logo_image`
*   `subtitle_track`
*   `background_style`
*   `brand_theme`

แต่ละ template สามารถตีความ slot ต่างกันได้ แต่ชื่อ slot กลางควรเหมือนกัน เพื่อให้ API และ UI เรียบง่าย

### 8.5 Job Request Contract
V1 ควรกำหนด request model ให้ชัดเจนพอสำหรับ upload + render

**Suggested job request fields:**
*   `source_video`
*   `intro_video` (optional)
*   `outro_video` (optional)
*   `logo_image` (optional)
*   `subtitle_file` (optional)
*   `template_family` = `auto | vertical | horizontal`
*   `template_variant` (optional)
*   `brand_theme` (optional)
*   `subtitle_theme` (optional)
*   `created_by`

### 8.6 Internal Normalized Render Spec
หลังผ่าน validation แล้ว API service ควรแปลง request ให้เป็น normalized render spec กลางก่อนส่งต่อให้ Hyperframes renderer

**Suggested normalized render spec:**
```json
{
    "job_id": "job_xxx",
    "template_family": "vertical",
    "template_variant": "default",
    "orientation_detected": "vertical",
    "assets": {
        "source_video": "object://...",
        "intro_video": "object://...",
        "outro_video": "object://...",
        "logo_image": "object://...",
        "subtitle_file": "object://..."
    },
    "composition": {
        "brand_theme": "default",
        "subtitle_theme": "glassmorphism",
        "safe_zone_profile": "vertical_default"
    }
}
```

### 8.7 Subtitle Input Design
สำหรับ kinetic subtitles ระบบควรใช้ JSON ที่มี word-level timestamps เป็น format หลักใน V1

**Suggested word-level JSON model:**
```json
{
    "segments": [
        {
            "start": 0.2,
            "end": 2.4,
            "text": "hello world",
            "words": [
                { "word": "hello", "start": 0.2, "end": 0.8 },
                { "word": "world", "start": 0.9, "end": 1.4 }
            ]
        }
    ]
}
```

**SRT handling recommendation:**
*   รองรับ SRT ได้เฉพาะในฐานะ subtitle import format
*   ถ้าไม่มี word-level timing ให้ระบบใช้ fallback subtitle animation ที่ระดับวลี ไม่ใช่ word-by-word kinetic mode

### 8.8 Branding Design Rules
V1 ควรใช้ placement preset ต่อ template แทน face-aware dynamic placement เพื่อควบคุมความซับซ้อน

**Recommended approach:**
*   Vertical template มี logo anchor ที่ออกแบบเฉพาะสำหรับ 9:16
*   Horizontal template มี logo anchor ที่เหมาะกับ framed layout ของ 16:9-in-vertical composition
*   opacity, size, margin และ z-index ต้องถูกกำหนดเป็น theme tokens ไม่ hardcode กระจายหลายจุด

### 8.9 Intro / Outro Timing Rules
*   Intro เล่นก่อน main video เสมอ
*   Outro เล่นทันทีเมื่อ main video จบ
*   ความยาวของ main video เป็น dynamic input
*   Transition timing ต้องถูกคำนวณจาก duration จริงของ clip ที่ถูกใช้งาน

### 8.10 API Endpoints
V1 ควรมี endpoint ขั้นต่ำดังนี้:

*   `POST /hyperframes/jobs` สร้าง render job
*   `GET /hyperframes/jobs/{job_id}` ดูสถานะ job
*   `GET /hyperframes/jobs/{job_id}/output` ดาวน์โหลด output
*   `GET /hyperframes/jobs/{job_id}/artifacts/{artifact_key}` ดึง artifact เพิ่มเติม เช่น normalized spec หรือ subtitle preview data

### 8.11 Job State Model
**Suggested states:**
*   `created`
*   `queued`
*   `rendering`
*   `completed`
*   `failed`

**Suggested job status response fields:**
*   `job_id`
*   `status`
*   `template_family`
*   `template_variant`
*   `orientation_detected`
*   `progress_percent`
*   `output_url`
*   `error_code`
*   `error_message`

### 8.12 Error Handling
V1 ควรมี error categories อย่างน้อยดังนี้:
*   `invalid_input`
*   `unsupported_video_format`
*   `asset_upload_failed`
*   `template_resolution_failed`
*   `subtitle_parse_failed`
*   `render_failed`
*   `output_store_failed`

Frontend ควรแสดง error summary ที่อ่านง่าย ส่วน backend ควรเก็บ technical details สำหรับ log/debug

### 8.13 Performance and Limits
V1 ควรกำหนด operational guardrails ตั้งแต่ต้น แม้จะยังไม่ finalize ตัวเลข production

**Recommended initial constraints:**
*   จำกัดความยาววิดีโอ input สูงสุดสำหรับ V1
*   จำกัดขนาดไฟล์ upload สูงสุด
*   จำกัดจำนวน concurrent render jobs ต่อ worker
*   timeout งาน render ต่อ job
*   retention policy ของ output และ uploaded assets

ตัวเลขจริงควรถูกกำหนดใน implementation planning ตามเครื่องและ infra ที่ทีมมี

### 8.14 Testing Strategy
*   **Template Router Tests:** ตรวจว่า input แนวตั้ง/แนวนอน route ถูก family
*   **Composition Builder Tests:** ตรวจว่า assets และ config ถูก map เข้า slot ถูกต้อง
*   **API Validation Tests:** ตรวจ request ที่ขาด field หรือ format ผิด
*   **Render Smoke Tests:** ใช้ fixture วิดีโอสั้นเพื่อยืนยันว่า Hyperframes render ได้จริง
*   **Golden Output Tests:** ใช้ sample jobs ที่ล็อก expected output behavior ของ vertical/horizontal templates

### 8.15 V1 Non-Goals
สิ่งต่อไปนี้ควรถือเป็นนอกขอบเขตของ V1 เพื่อลด risk:
*   การเชื่อม orchestrator เดิมแบบเต็มรูปแบบ
*   auto subtitle generation จาก ASR ภายใน service นี้เอง
*   face-aware smart logo placement
*   advanced adaptive layout หลายสิบ template variants
*   collaborative editing หรือ timeline editor เต็มรูปแบบ

## 9. Implementation Notes For Team

### 9.1 Why Hyperframes
Hyperframes เหมาะกับงานนี้เพราะ composition ของ intro/outro, branding, subtitle animation และ layered layout สามารถพัฒนาในรูปแบบ HTML/CSS/JS ได้เร็วกว่า render logic แบบ low-level video filter เพียงอย่างเดียว และเหมาะกับการมี template แยก vertical/horizontal อย่างชัดเจน

### 9.2 Recommended First Milestone
Milestone แรกควรส่งมอบให้ได้ดังนี้:
*   Upload main video
*   Detect orientation
*   Route ไปยัง vertical หรือ horizontal template
*   Render พร้อม logo และ subtitle JSON ขั้นพื้นฐาน
*   Export MP4 ได้สำเร็จ

### 9.3 Recommended Second Milestone
*   เพิ่ม intro/outro sequencing
*   เพิ่ม template variants
*   เพิ่ม brand theme tokens
*   เพิ่ม artifact/debug view สำหรับ normalized render spec