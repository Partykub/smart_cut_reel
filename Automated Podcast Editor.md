# Automated Podcast Editor - Architecture Specification

**Document Version:** 1.1 (Production-Ready Draft)  
**Project:** ระบบตัดต่อ Podcast อัตโนมัติรองรับ Multi-camera และ Auto-reframing

## 1. System Overview (ภาพรวมระบบ)

ระบบออกแบบมาเพื่อรับไฟล์วิดีโอ (1-5 ไฟล์) และไฟล์เสียง ทำการซิงค์ข้อมูล วิเคราะห์เสียงผู้พูดด้วย AI (Voice Activity Detection & Speaker Diarization) เพื่อสร้างแผนการตัดต่อ (Timeline) จากนั้นนำ Timeline ไปดัดแปลงตามฟีเจอร์ที่ผู้ใช้เลือก (Optional Features) โดยมีระบบให้ผู้ใช้ตรวจสอบความถูกต้องก่อนส่งให้ Video Engine (FFmpeg) ประมวลผลออกมาเป็นไฟล์วิดีโอที่ตัดต่อเสร็จสมบูรณ์ หรือส่งออกเป็นไฟล์โปรเจกต์สำหรับโปรแกรมตัดต่อมืออาชีพ

สถาปัตยกรรมใช้รูปแบบ Pipeline Pattern แยกการทำงานออกเป็น 3 ส่วนหลัก:

- **Logic Validation:** ตรวจสอบและดักจับความผิดพลาด (Guardrails)
- **Common Core:** แกนหลักในการประมวลผลที่ต้องทำงานเสมอ
- **Optional Features:** โมดูลเสริมที่เปิด/ปิดได้ตามการตั้งค่า

## 2. Logic Validation (ด่านตรวจสอบเงื่อนไขก่อนประมวลผล)

ทำงานทันทีหลังจากผู้ใช้อัปโหลดไฟล์และกด Submit หากไม่ผ่านเงื่อนไข ระบบจะแจ้งเตือนหรือปรับโหมดอัตโนมัติ

### V-01: Camera Count & Mode Selection (ตรวจสอบจำนวนกล้อง)

**เงื่อนไข:** `count(input_videos) == 1`  
**Action:** บังคับเข้าโหมด "Jump Cut Editor"  
**UI Update:** Disable ฟีเจอร์การกำหนดบทบาทกล้อง (Host, Guest, Wide) และ Disable ฟีเจอร์ "Split-screen"

**เงื่อนไข:** `1 < count(input_videos) <= 5`  
**Action:** บังคับเข้าโหมด "Multi-cam Editor"  
**Validation:** ต้องตรวจสอบว่ามีการกำหนด Role `Wide_Shot` หรือไม่ (Require อย่างน้อย 1 Wide Shot เป็น Fallback)

### V-02: Master Audio Selection (เลือกเส้นเสียงหลัก)

**Validation:** หากมีหลายไฟล์ (รวมถึงไฟล์เสียงแยก) ต้องบังคับให้ผู้ใช้ตั้งค่า `is_master_audio = true` ให้กับไฟล์ใดไฟล์หนึ่งเพียงไฟล์เดียว เสียงจากไฟล์อื่นจะต้องถูกตั้งสถานะเป็น `mute_in_render = true`

### V-03: Resolution & Framerate Normalization (จัดการมาตรฐานไฟล์)

**Action:** อ่าน Metadata ทุกไฟล์ หากพบความแตกต่างของ Resolution หรือ FPS ให้ตั้งค่างานใน Pre-processing ให้แปลงไฟล์ทั้งหมดไปยึดตามค่าของไฟล์ `Wide_Shot`

### V-04: Aspect Ratio Conflict (ตรวจสอบสัดส่วนภาพ)

**เงื่อนไข:** `input_aspect_ratio == 16:9 AND target_output == 9:16`  
**Action:** บังคับให้ตั้งค่า `feature_auto_reframe = true` อัตโนมัติ (ไม่สามารถปิดได้)

**เงื่อนไข:** `input_aspect_ratio == 9:16 AND target_output == 16:9`  
**Action:** แจ้งเตือนผู้ใช้ (Warning) และบังคับเลือกรูปแบบการแก้ไข: `[Pad_Black_Bars | Blurred_Background]`

## 3. Common Core (แกนประมวลผลหลัก - ทำงานเสมอ)

ลำดับการทำงานหลักของระบบ ไม่ว่าผู้ใช้จะตั้งค่าอย่างไร Pipeline นี้ต้องถูกประมวลผลตามลำดับต่อไปนี้

### Media Demuxing & Extraction

แยกสกัด Audio track จากไฟล์วิดีโอที่เป็น Master Audio และไฟล์วิดีโออื่นๆ เพื่อเตรียมไว้สำหรับขั้นตอน Sync และ AI Analysis

### Audio Synchronization (รันเมื่อ Input > 1)

นำคลื่นเสียง (Waveform) จากกล้องย่อย มาทำ Cross-correlation เทียบกับ Master Audio เพื่อหาค่า Offset (Delay) ของแต่ละกล้อง

บันทึกค่า Offset ของแต่ละกล้องไว้ในหน่วยวินาที

### AI Audio Analysis

- **Voice Activity Detection (VAD):** สแกน Master Audio เพื่อระบุช่วงเวลา (Timestamps) ที่มีเสียงมนุษย์ (Speech) และไม่มีเสียงมนุษย์ (Silence)
- **Speaker Diarization:** รันโมเดล (เช่น Pyannote) เพื่อระบุตัวตน (Speaker_ID) ในแต่ละช่วงที่มีเสียงมนุษย์ เช่น `[Speaker_1, Speaker_2]`

### Base Timeline Generation

สร้าง JSON/Dictionary ที่เก็บแผนการตัดต่อแบบดิบ (Raw Plan) โดยแมป `Speaker_ID` เข้ากับ `Camera_Role`

### Human-in-the-Loop (Review & Edit Timeline)

- ส่งข้อมูล Timeline JSON ไปยัง Frontend เพื่อแสดงผลเป็นบล็อกเวลา (Visual Timeline)
- อนุญาตให้ผู้ใช้ตรวจสอบความถูกต้อง ปรับเลื่อนจุดตัด (Trim) หรือสลับมุมกล้องเองแบบ Manual (Override AI)
- รอให้ผู้ใช้กด "Confirm Render" จึงจะส่งข้อมูล Optimized Timeline ไปยังกระบวนการถัดไป

### FFmpeg Renderer (Execution)

- รับ Timeline สุดท้ายมาสร้างคำสั่ง `filter_complex`
- ดำเนินการต่อคลิป (Concat), ตัดเสียง (Mute), ซิงค์ภาพตาม Offset, และเข้ารหัสเป็นไฟล์ปลายทาง (`.mp4`)

## 4. Optional Features (ฟีเจอร์ที่เปิด/ปิดได้ผ่าน Checkbox)

โมดูลเหล่านี้ทำหน้าที่เป็น "Middleware" ที่รับ Timeline เข้ามาดัดแปลง (Transform) ก่อนนำไปแสดงผลหรือ Render

### F-01: Remove Dead Air (ตัดช่วงเดดแอร์)

**Trigger:** Checkbox "ตัดช่องว่างอัตโนมัติ" = `true`  
**Logic:** ลบ Object ใน Timeline ที่มีสถานะเป็น `silence` เกินกว่า Threshold แล้วขยับเวลาของคลิปให้ติดกัน (Jump Cut)

### F-02: Auto-Reframe 9:16 (ตามติดผู้พูดแนวตั้ง)

**Trigger:** Target Output = `9:16`  
**Logic (Post-processing):** นำไฟล์ที่ Render แนวนอน 16:9 เสร็จแล้ว มารันผ่านโมเดล YOLO เพื่อหา Center X ของผู้พูด และใช้คำสั่ง Crop ขนาด 9:16 แบบติดตามตัวบุคคลอย่างนุ่มนวล

### F-03: Dynamic Split-Screen (แบ่งจอเมื่อพูดแทรก)

**Trigger:** Checkbox "แบ่งจอเมื่อพูดพร้อมกัน" = `true`  
**Logic:** เปลี่ยนค่า `source` ในช่วงที่เกิด overlap ให้กลายเป็นฟังก์ชันสเกลภาพ 2 กล้องมาประกบกัน

### F-04: Reaction Shot (สลับภาพคนฟัง)

**Trigger:** Checkbox "สลับภาพผู้ฟังแก้เบื่อ" = `true`  
**Logic:** แทรก Object ตัดสลับไปหาคนฟังประมาณ 2-3 วินาที หากตรวจพบการพูดต่อเนื่องเกิน Threshold (เช่น `>15s`)

### F-05: Professional Export (ส่งออกไฟล์โปรเจกต์)

**Trigger:** Checkbox "ส่งออกสำหรับ Premiere Pro / DaVinci Resolve" = `true`  
**Logic:** ระบบจะไม่ Render วิดีโอใหม่แบบเต็มรูปแบบ แต่จะทำเพียงแค่แปลงข้อมูล Timeline JSON ให้เป็นฟอร์แมต XML (FCPXML) หรือ EDL เพื่อให้ผู้ใช้ดาวน์โหลดไปทำต่อในโปรแกรมตัดต่อมืออาชีพได้ทันที

### F-06: Auto-Audio Polish (ปรับแต่งเสียงระดับโปร)

**Trigger:** Checkbox "ปรับแต่งคุณภาพเสียงอัตโนมัติ" = `true`  
**Logic:** สั่งให้ FFmpeg ทำงานเพิ่มเติม 3 อย่างกับ Master Audio:

1. Normalize ความดังให้อยู่ที่ -16 LUFS
2. ใช้ Noise Gate ลบเสียงจี่/รบกวนรอบข้าง
3. หากมี Music Track แทรก จะทำการ Auto-Ducking (หลบเสียงดนตรีลงเมื่อมีคนพูด)

## 5. Technology Stack Recommendations

- **Audio AI:** Pyannote.audio (Diarization ผ่าน PyTorch/CUDA เมื่อมี GPU), Silero VAD (Silence Detection)
- **Vision AI:** YOLOv8/YOLOv11 (Person Detection สำหรับ Auto-Reframe)
- **Video Processing:** FFmpeg + ffmpeg-python + ffprobe โดยใช้ build ที่รองรับ NVENC/QSV สำหรับ hardware acceleration
- **Core Backend:** Python (ประมวลผลวิดีโอและ AI) / Go (สำหรับ API Server และ Job Queue)
- **Frontend:** React / Next.js (สำหรับสร้าง GUI ลากวาง Timeline คล้าย Video Editor)

## 6. Advanced System Architecture & Performance

ข้อกำหนดในการจัดการทรัพยากรระดับ Production เพื่อให้ระบบทำงานได้เสถียรและรวดเร็วเมื่อเจอไฟล์ขนาดใหญ่ (เช่น คลิปยาว 1-2 ชั่วโมง)

### 6.1 Performance & Scalability (การจัดการประสิทธิภาพ)

- **Audio Chunking Processing:** ระบบจะไม่ส่งไฟล์เสียงยาว 1 ชั่วโมงเข้า AI รวดเดียว แต่จะซอย (Chunk) เป็นไฟล์ละ 10 นาที แล้วส่งให้ AI รันแบบ Parallel เพื่อลดเวลาและประหยัด RAM/VRAM
- **Hardware Acceleration:** การ Render ผ่าน FFmpeg ต้องบังคับใช้ GPU Encoding (เช่น `h264_nvenc` สำหรับชิป NVIDIA) เพื่อเพิ่มความเร็วในการ Export ให้ไวกว่า CPU หลายเท่าตัว
- **GPU-First Runtime Selection:** ระบบต้องตรวจ capability ของเครื่องทุกครั้งก่อนเริ่ม job และเลือก backend ตามลำดับ `NVIDIA NVENC/CUDA -> Intel Quick Sync -> CPU` พร้อมบันทึก backend ที่เลือกใช้ไว้ใน job metadata
- **AI Acceleration Policy:** งาน AI ที่ได้ประโยชน์จาก GPU เช่น Speaker Diarization และ Auto-Reframe Detection ควรใช้ CUDA เป็นค่าเริ่มต้น ส่วนงานที่ lightweight หรือไม่คุ้มค่าในการย้ายขึ้น GPU เช่น metadata probing ยังใช้ CPU ได้ตามปกติ
- **Runtime Prerequisite:** เครื่องที่รัน pipeline ต้องมี `ffmpeg` และ `ffprobe` พร้อมใช้งานเสมอ และถ้าต้องการเส้นทาง NVIDIA ต้องใช้ FFmpeg build ที่เปิด encoder/decoder แบบ NVENC ได้จริง
- **Fallback Contract:** หากไม่พบ backend ที่ต้องการ ระบบต้อง downgrade อย่างปลอดภัยโดยไม่เปลี่ยนผลลัพธ์เชิงตรรกะของ Timeline เช่น render ใช้ `libx264`, vision inference ใช้ CPU, แต่ validation และ manifest ต้องยังเดินต่อได้เหมือนเดิม

### 6.2 Storage Lifecycle Management (ระบบจัดการพื้นที่เซิร์ฟเวอร์)

มีการรัน Background Worker (เช่น Cronjob) สำหรับกวาดล้างไฟล์เสมอ:

- **Intermediate cleanup:** ลบไฟล์ขยะที่เกิดระหว่างทาง (เช่น ไฟล์เสียงที่แยกมา, ไฟล์วิดีโอหั่นย่อย) ทันทีหลัง Render งานเสร็จ
- **Source & Output lifecycle:** ตั้งเวลาลบไฟล์ต้นฉบับของผู้ใช้และไฟล์วิดีโอที่ Render เสร็จแล้วอัตโนมัติภายในระยะเวลาที่กำหนด (เช่น 7 วันหลังประมวลผลสำเร็จ) เพื่อคืนพื้นที่ความจุให้กับระบบ