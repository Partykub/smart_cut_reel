# Hyperframes Product Flow

## 1. Objective

เอกสารนี้สรุป product flow ที่เหมาะสมที่สุดสำหรับการใช้งาน Hyperframes ร่วมกับ Smart Cut Reel โดยใช้ข้อดีของทั้งสองฝั่งร่วมกันให้เกิดประสิทธิภาพสูงสุด

แนวคิดหลักคือ:

* Smart Cut Reel เป็น **workflow + orchestration layer**
* Hyperframes Studio เป็น **editing + preview layer**

เป้าหมายไม่ใช่แค่ให้ผู้ใช้อัปโหลดไฟล์แล้วกด render แต่ต้องรองรับการทำงานแบบ project-based ที่สามารถกลับมาแก้ไข, iterate, และ render ใหม่ได้หลายรอบอย่างเป็นระบบ

## 2. Product Positioning

### 2.1 Smart Cut Reel รับผิดชอบอะไร

Smart Cut Reel ควรเป็นชั้นที่รับผิดชอบงานเชิง product และ production workflow ได้แก่:

* asset intake
* source validation
* subtitle validation
* template routing
* brand preset selection
* project and revision management
* render queue and job tracking
* artifact storage
* output delivery
* business rules and safety checks

### 2.2 Hyperframes Studio รับผิดชอบอะไร

Hyperframes Studio ควรเป็นชั้นที่รับผิดชอบงานเชิง editor ได้แก่:

* timeline editing
* preview and playback control
* layer and clip inspection
* source editing
* block-based composition editing
* timing and animation adjustment

### 2.3 สิ่งที่ไม่ควรทำซ้ำ

หากตัดสินใจใช้ Hyperframes Studio จริงจัง ควรหลีกเลี่ยงการสร้างสิ่งเหล่านี้ซ้ำใน Smart Cut Reel:

* custom timeline editor
* custom clip/layer inspector
* custom source editor
* custom preview player สำหรับ composition editor

สิ่งเหล่านี้ Hyperframes Studio ทำได้โดยตรงอยู่แล้ว และหากสร้างซ้ำจะทำให้ product ซ้ำซ้อนทั้งในเชิง UX และ implementation cost

## 3. Recommended Product Model

ระบบควรเปลี่ยนจาก **Job-first** ไปเป็น **Project-first**

### 3.1 Current model

ปัจจุบัน flow มีลักษณะใกล้เคียงกับ:

* Upload assets
* Create render job
* Wait for completion
* Download result

โมเดลนี้เหมาะกับ one-shot rendering แต่ไม่เหมาะกับงานที่ต้องแก้ไขหลายรอบผ่าน Studio

### 3.2 Recommended model

ควรเปลี่ยนเป็น:

* Create project
* Prepare assets and scaffold workspace
* Open in Studio
* Save revision
* Render draft/final
* Review output
* Iterate

## 4. Core Domain Objects

ระบบควรมี object หลัก 3 ตัว

### 4.1 Project

ตัวแทนของงานวิดีโอหนึ่งชิ้น เช่น:

* Bugaboo promo cut
* Channel intro package
* Episode teaser vertical cut

ข้อมูลระดับ project ที่ควรมี:

* project_id
* name
* owner
* created_at
* updated_at
* source metadata summary
* orientation mode
* brand preset
* active revision id

### 4.2 Revision

Revision คือ snapshot ของ composition state ในช่วงเวลาหนึ่ง

ข้อมูลที่ควรมี:

* revision_id
* project_id
* revision_name
* revision_type เช่น draft, named, final-candidate
* workspace path or manifest
* asset references
* composition references
* created_at
* created_by
* notes

Revision ต้องใช้เป็นจุดอ้างอิงสำหรับ render ทุกครั้ง เพื่อให้ย้อนกลับได้ว่า output มาจากสภาพงานเวอร์ชันไหน

### 4.3 Render Job

Render Job คือกระบวนการ export output จาก revision ใด revision หนึ่ง

ข้อมูลที่ควรมี:

* job_id
* project_id
* revision_id
* render mode เช่น draft/final
* status
* progress_percent
* output_url
* artifact manifest
* error_code
* error_message
* created_at
* updated_at

## 5. End-to-End Flow

### 5.1 Step 1: Create Project

ผู้ใช้เริ่มจากการสร้าง project ใหม่ ไม่ใช่การสร้าง render job ทันที

ข้อมูลที่ผู้ใช้กรอก:

* project name
* source video
* logo image
* optional subtitle file
* optional intro/outro asset
* brand preset
* orientation mode หรือ auto

ระบบทำงานอัตโนมัติ:

* probe source metadata
* detect orientation
* validate subtitle file
* normalize assets
* choose template family
* scaffold initial Hyperframes workspace
* create first revision

ผลลัพธ์ของขั้นตอนนี้:

* ได้ project
* ได้ revision แรก
* พร้อม action ต่อไป เช่น `Open in Studio` หรือ `Render Draft`

### 5.2 Step 2: Project Overview

หลังสร้าง project แล้ว ผู้ใช้เข้าสู่หน้ารวมข้อมูลของ project

หน้าจอนี้ควรแสดง:

* project header
* source summary
* asset summary
* active revision
* render history
* action buttons

CTA หลักควรมี:

* Open in Studio
* Save revision
* Render Draft
* Render Final
* Replace assets

### 5.3 Step 3: Open in Studio

เมื่อผู้ใช้เปิด Studio ระบบควรเปิด Hyperframes Studio บน workspace เดียวกับ project revision ปัจจุบัน

สิ่งที่ผู้ใช้ควรทำได้:

* preview composition
* scrub timeline
* adjust timing
* move clips
* edit source HTML
* modify intro/outro block
* change overlay placement
* inspect clip structure

ในระดับ product shell ของ Smart Cut Reel ควรครอบ Studio ด้วยข้อมูลต่อไปนี้:

* project name
* active revision
* save state
* render draft button
* back to project button

### 5.4 Step 4: Save Revision

การแก้ใน Studio ต้องไม่เป็นเพียงการแก้ไฟล์แบบไม่มี history

ควรมีการ save แบบสองระดับ:

* auto-save draft
* save named revision

ตัวอย่างชื่อ revision:

* Draft
* Revision 2 - intro tightened
* Revision 3 - subtitle cleanup

ทุกครั้งที่ save named revision ควรสร้าง snapshot ใหม่อย่างชัดเจน

### 5.5 Step 5: Render

เมื่อผู้ใช้พร้อม export ระบบควรแยก render mode อย่างน้อย 2 แบบ:

* Render Draft
* Render Final

#### Render Draft

ใช้สำหรับ:

* ตรวจ timing
* ตรวจ subtitle placement
* ตรวจ layout และ branding
* ตรวจ scene transition

#### Render Final

ใช้สำหรับ:

* งานส่งมอบจริง
* output quality สูงกว่า
* export ที่พร้อมเผยแพร่

ทุก render job ต้องผูกกับ revision เดียวอย่างชัดเจน

### 5.6 Step 6: Review Output

หลัง render เสร็จ ผู้ใช้ไม่ควรเห็นแค่ปุ่มดาวน์โหลดอย่างเดียว แต่ควรมีตัวเลือกต่อยอด เช่น:

* Download MP4
* Open source revision
* Duplicate revision
* Render again
* Mark as final candidate

## 6. Recommended Screens

### 6.1 Projects List

สำหรับแสดงรายการ project ทั้งหมด

ควรมีข้อมูลต่อ card:

* project name
* source thumbnail
* last updated
* active revision
* latest render status
* quick actions

### 6.2 New Project

หน้าสำหรับรับ asset และตั้งค่าเบื้องต้น

หน้าจอนี้ไม่ควรใช้ชื่อว่า Studio เพราะยังเป็นขั้น intake/setup

ชื่อที่เหมาะกว่า:

* New Project
* Project Setup
* Hyperframes Project Setup

### 6.3 Project Detail

หน้าหลักของ project ที่แสดง:

* project metadata
* assets
* active revision
* revision list
* render history
* CTA หลัก

### 6.4 Studio View

หน้าหรือ surface สำหรับ editing composition โดยใช้ Hyperframes Studio

### 6.5 Render Job View

ใช้แสดง:

* job status
* progress
* output preview
* artifacts
* linked revision
* rerun actions

## 7. UX Role Separation

เพื่อให้ผู้ใช้ไม่สับสน ควรแยกบทบาทของแต่ละหน้าให้ชัด

### 7.1 Setup

หน้าที่:

* รับ asset
* ตั้งค่าเบื้องต้น
* สร้าง project

### 7.2 Edit

หน้าที่:

* ปรับ composition
* preview
* save revisions

### 7.3 Render

หน้าที่:

* เลือก render mode
* เริ่ม render
* ติดตามสถานะ

### 7.4 Review

หน้าที่:

* ตรวจ output
* compare revisions/renders
* download final output

## 8. Where to Keep Existing Functionality

### 8.1 Keep in Smart Cut Reel

ฟังก์ชันที่ควรอยู่กับ Smart Cut Reel ต่อไป:

* asset upload
* asset normalization
* subtitle contract validation
* orientation detection
* template family routing
* brand preset mapping
* intro/outro automation rules
* project creation
* revision management
* render queue
* artifact manifest and output storage

### 8.2 Delegate to Hyperframes Studio

ฟังก์ชันที่ควรพึ่ง Studio:

* timeline editing
* preview playback
* composition file editing
* clip arrangement
* block inspection
* visual authoring

## 9. Preset Strategy

ระบบควรมี preset 3 ชั้น

### 9.1 Brand Preset

กำหนด:

* typography
* color system
* logo treatment
* subtitle styling defaults
* intro/outro visual language

### 9.2 Template Preset

กำหนด:

* vertical layout
* horizontal layout
* safe zone profile
* logo placement preset
* subtitle placement preset

### 9.3 Output Preset

กำหนด:

* draft quality
* final quality
* social export target

## 10. Recommended Automation

เพื่อให้ product มีประสิทธิภาพสูง ควรให้ระบบทำงานอัตโนมัติในสิ่งที่คาดเดาได้ดี

### 10.1 Intake Automation

* auto-detect orientation
* auto-validate subtitle structure
* auto-choose template family
* auto-place logo using preset

### 10.2 Composition Automation

* auto-generate first intro from logo
* auto-create first revision
* auto-load source into workspace
* auto-attach subtitles when available

### 10.3 Render Automation

* auto-snapshot revision before render
* auto-generate draft after first successful save (optional future)
* auto-persist artifact manifest and render logs

## 11. Error Flow Design

ระบบต้องมี flow รองรับกรณี error อย่างชัดเจน

### 11.1 Common Failure States

* source media unreadable
* subtitle invalid
* logo missing or unsupported
* studio workspace unavailable
* render failed
* output artifact missing

### 11.2 Recovery Actions

ทุกกรณีควรมี CTA ฟื้นตัวที่ชัด เช่น:

* Replace file
* Retry render
* Rebuild workspace
* Open revision
* Return to project

## 12. Suggested Information Architecture

### 12.1 Navigation

โครงเมนูที่แนะนำ:

* Projects
* New Project
* Project Detail
* Studio
* Render Jobs
* Settings / Presets

### 12.2 URL Structure

ตัวอย่าง route structure ที่เหมาะสม:

* `/hyperframes/projects`
* `/hyperframes/new`
* `/hyperframes/projects/[projectId]`
* `/hyperframes/projects/[projectId]/studio`
* `/hyperframes/jobs/[jobId]`

## 13. Practical Rollout Plan

เพื่อไม่ต้องรื้อระบบทั้งหมดในครั้งเดียว ควรแบ่ง rollout เป็น 3 ระยะ

### Phase 1: UX Separation

เป้าหมาย:

* แยก `Project Setup` ออกจาก `Render Job`
* เพิ่ม `Project Detail` เป็นหน้ากลาง
* ฝังหรือเปิด Hyperframes Studio จาก project

ผลลัพธ์:

* ผู้ใช้เริ่มเข้าใจ product model แบบ project-based

### Phase 2: Shared Workspace

เป้าหมาย:

* ให้ project create สร้าง Hyperframes workspace จริง
* ให้ Studio เปิด workspace เดียวกับ revision ปัจจุบัน
* ให้ render pipeline ใช้ workspace เดียวกัน

ผลลัพธ์:

* preview และ render ใช้ source of truth เดียวกัน

### Phase 3: Revision-first Rendering

เป้าหมาย:

* render ทุกครั้งจาก revision snapshot
* เก็บ render history ต่อ revision
* เปิดทาง compare iteration ได้ในอนาคต

ผลลัพธ์:

* product พร้อมสำหรับ production workflow มากขึ้น

## 14. Immediate Recommendation

สิ่งที่ควรทำต่อทันทีโดยไม่รื้อทั้งหมด:

1. เปลี่ยนหน้า `/hyperframes` จากหน้าที่ทำทุกอย่าง เป็นหน้าที่เน้น setup หรือ routing
2. เพิ่ม `Project Overview` เป็นหน้ากลาง
3. เปลี่ยน flow จาก `upload -> job page` เป็น `upload -> project overview`
4. ให้ผู้ใช้เลือกต่อว่า `Open in Studio` หรือ `Render Draft`
5. ค่อย refactor backend ให้ render อิง revision มากขึ้นในลำดับถัดไป

## 15. Summary

แนวทางที่ดีที่สุดสำหรับ product นี้คือ:

* ใช้ Smart Cut Reel เป็นระบบควบคุมงาน, validate, queue, และจัดการ output
* ใช้ Hyperframes Studio เป็นระบบแก้ composition และ preview
* เปลี่ยน product model เป็น project-first พร้อม revisions และ render jobs
* ไม่ทำ editor functionality ซ้ำกับ Hyperframes Studio
* ลงทุนที่ automation, presets, revision management, และ render reliability แทน

หากทำตามแนวทางนี้ product จะได้ทั้งความยืดหยุ่นของ editor และความแข็งแรงของ production workflow ในระบบเดียว