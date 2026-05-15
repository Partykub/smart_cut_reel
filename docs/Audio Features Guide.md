# คู่มือฟีเจอร์เสียง (Audio Features Guide)

เอกสารนี้สรุปฟีเจอร์เสียงใน **Smart Cut Reel** ณ โค้ดปัจจุบัน — สำหรับอ่านทำความเข้าใจการตั้งค่า, เครื่องมือที่ใช้, logic การประมวลผล, คำศัพท์, ผลลัพธ์ที่ได้, และการอ่าน UI (รวม waveform / peak window)

**เกี่ยวข้องกับ:** `Phase 2 Todo - Dead Air Cutting.md`, `Phase 3 Todo - Audio Quality Chain.md`, `services/audio_enhancement/`, `frontend/src/components/UploadForm.tsx`, `frontend/src/components/AudioOutputInsightPanel.tsx`

---

## สารบัญ

1. [ภาพรวม](#1-ภาพรวม)
2. [ฟีเจอร์ที่ผู้ใช้เลือกได้ (หน้าอัปโหลด)](#2-ฟีเจอร์ที่ผู้ใช้เลือกได้-หน้าอัปโหลด)
3. [Pipeline และลำดับขั้น](#3-pipeline-และลำดับขั้น)
4. [เครื่องมือและเทคโนโลยี](#4-เครื่องมือและเทคโนโลยี)
5. [Logic ตามการตั้งค่า](#5-logic-ตามการตั้งค่า)
6. [LUFS กับ peak dBFS (อ่านสองมิติให้เป็น)](#6-lufs-กับ-peak-dbfs-อ่านสองมิติให้เป็น)
7. [Peak window และ peak-force](#7-peak-window-และ-peak-force)
8. [สิ่งที่เห็นใน UI หลัง job เสร็จ](#8-สิ่งที่เห็นใน-ui-หลัง-job-เสร็จ)
9. [Waveform และเส้นอ้างอิง dBFS](#9-waveform-และเส้นอ้างอิง-dbfs)
10. [Metrics และ warnings](#10-metrics-และ-warnings)
11. [Config keys (API / manifest)](#11-config-keys-api--manifest)
12. [พจนานุกรมคำศัพท์](#12-พจนานุกรมคำศัพท์)
13. [ตัวอย่างเคสจริง](#13-ตัวอย่างเคสจริง)
14. [Logic และสมการราย Feature (อ้างอิงโค้ด)](#14-logic-และสมการราย-feature-อ้างอิงโค้ด)
15. [ข้อจำกัดที่ควรรู้](#15-ข้อจำกัดที่ควรรู้)

---

## 1. ภาพรวม

Smart Cut Reel ไม่ได้ “แค่ตัดวิดีโอแนวตั้ง” — preset หลักที่ UI ใช้ (`reframe_16x9_to_9x16_dead_air_enhanced`) มี **chain เสียง** ก่อน reframe:

1. ดึงเสียงจากวิดีโอ → WAV
2. ปรับคุณภาพ/ความดัง (optional ตาม profile)
3. ตรวจจับช่วงพูด/เงียบ (VAD)
4. วางแผนตัด dead air (optional)
5. Reframe + render MP4 9:16 โดย mux เสียงที่ปรับแล้ว (หรือเสียงต้นทาง ตาม profile)

**แนวคิดสำคัญ:** ระบบแยก **ความดังโดยรวม (LUFS)** กับ **ยอด peak สูงสุด (dBFS)** เป็นคนละขั้น — ไม่ใช่ตัวเลขเดียวกัน

---

## 2. ฟีเจอร์ที่ผู้ใช้เลือกได้ (หน้าอัปโหลด)

### 2.1 สไตล์เสียง MP4 (`audio_profile`)

| ค่า | ชื่อใน UI | loudnorm | เป้า LUFS โดยประมาณ | MP4 ใช้เสียง |
|-----|-----------|----------|----------------------|--------------|
| `original` | Source (embedded track) | ปิด | — | เสียงจากวิดีโอต้นทาง |
| `podcast` | Podcast (-16 LUFS) | เปิด | **-16** | `enhanced_audio.wav` |
| `social` | Social (-14 LUFS) | เปิด | **-14** | `enhanced_audio.wav` |
| `broadcast` | Broadcast (-23 LUFS) | เปิด | **-23** | `enhanced_audio.wav` |

โดย default profile ส่วนใหญ่ใช้ **loudnorm อย่างเดียว** (ไม่เปิด denoise / high-pass) เพื่อให้โทนเสียงใกล้ต้นทาง — เปิด noise reduction แยกได้

**พารามิเตอร์ loudnorm ที่ merge จาก profile** (เมื่อ loudnorm เปิด):

- `target_lufs` — เป้า integrated loudness
- `true_peak_db` — มัก **-1.5 dBTP** (true peak target ของ loudnorm)
- `loudness_range` — LRA (podcast/social ~11, broadcast ~7)

### 2.2 Noise reduction

- Toggle แยกจากสไตล์ LUFS
- เปิด → ส่ง `denoise_model: "std"` ไป `audio_enhancement` → FFmpeg **`afftdn`**
- ปิด → ไม่ใส่ denoise ใน chain (ยกเว้น profile อื่น override)

**ผลที่คาดหวัง:** ลด hum / hiss / room noise — อาจฟุ้งหรือ “แบน” ลงเล็กน้อยถ้าห้องเงียบอยู่แล้ว

### 2.3 บังคับ peak เข้า −18…−14 dBFS (peak-force)

- Toggle → `peak_force_to_window_enabled: true`
- หลัง **loudnorm** (และ filter อื่น) ระบบวัด peak ด้วย **astats** แล้วอาจรัน **`volume`** หนึ่งหรือหลายรอบจน peak อยู่ในช่วง
- **ค่าเริ่มต้นปัจจุบัน:** `peak_force_max_boost_db = 0` = **ไม่จำกัด boost** เมื่อเนื้อเงียบเกิน (ต่างจากช่วงแรกที่จำกัด +12 dB)

**ผลที่คาดหวัง:** ตัวเลข astats `peak_sample_dbfs` อยู่ในช่วง **[-18, -14]** — แต่ **LUFS อาจห่างจากเป้า profile** (มี warning)

### 2.4 Trim long silence (dead air)

- เปิด `remove_dead_air` → VAD + cut planning ตัดช่วงเงียบยาว
- เสียงที่วิเคราะห์มักเป็น **enhanced** (หลัง loudnorm) ก่อน VAD — ช่วยให้ silence detection เสถียรขึ้น

### 2.5 Pipeline ที่เกี่ยวข้อง (อ้างอิง)

| `pipeline_id` (ตัวอย่าง) | เสียง |
|-------------------------|--------|
| `reframe_16x9_to_9x16` | ไม่มี audio chain (vision-only) |
| `reframe_16x9_to_9x16_smooth_audio` | extract + enhance, ไม่ตัด dead air |
| `reframe_16x9_to_9x16_dead_air_enhanced` | extract + enhance + VAD + cut (UI หลัก) |
| `reframe_16x9_to_9x16_audio_quality` | เพิ่ม transcription + filler words |

---

## 3. Pipeline และลำดับขั้น

### 3.1 แผนภาพ (preset dead_air_enhanced)

```text
source.mp4 (16:9)
    │
    ▼
[validation] [media_metadata]
    │
    ▼
[audio_extraction]     FFmpeg → artifacts/extracted_audio.wav
    │
    ▼
[audio_enhancement]    FFmpeg: highpass? → afftdn? → loudnorm 2-pass → astats → volume?
    │                    → artifacts/enhanced_audio.wav
    ▼
[voice_activity_detection]   Silero VAD → artifacts/vad_segments.json
    │
    ▼
[dead_air_cut_planning]      → artifacts/cut_plan.json
    │
    ▼
[proxy_frame_sampling] … [body_detection] … [reframe] … [render_plan_compiler]
    │
    ▼
[ffmpeg_renderer]        MP4 9:16 + mux audio (มัก enhanced_wav)
    │
    ▼
outputs/final_9x16.mp4
```

### 3.2 ทำไม enhance ก่อน VAD

- Denoise + level ที่สม่ำเสมอช่วย VAD / ASR แม่นขึ้น (โดยเฉพาะห้องมี noise)
- Dead-air cut วางบน timeline ที่ “เสียงถูกปรับแล้ว” ให้สอดคล้องกับสิ่งที่ผู้ชมได้ยินใน MP4

---

## 4. เครื่องมือและเทคโนโลยี

| เครื่องมือ | ใช้ที่ไหน | หน้าที่ |
|------------|-----------|--------|
| **FFmpeg / ffprobe** | `audio_extraction`, `audio_enhancement`, `ffmpeg_renderer` | ดึงเสียง, filter, loudnorm, astats, volume, render |
| **loudnorm** (EBU R128) | `audio_enhancement` | ปรับ **LUFS** ตาม profile |
| **afftdn** | `audio_enhancement` (ถ้าเปิด denoise) | FFT denoise |
| **highpass** | `audio_enhancement` (ถ้า frequency > 0) | ตัด rumble ต่ำ |
| **astats** | `audio_enhancement` | วัด **Peak level dB** (overall) |
| **volume** | `audio_enhancement` (peak-force) | boost/attenuate ตาม dB |
| **Silero VAD** (ONNX) | `voice_activity_detection` | แบ่ง speech / silence |
| **faster-whisper** | `transcription` (preset audio_quality) | ASR + filler (ถ้าเปิด) |
| **Web Audio API** | Frontend | decode WAV สำหรับ waveform |

**Orchestrator** เรียก microservice ตาม `ORCHESTRATOR_SERVICE_ENDPOINTS` — local stack พอร์ต 8019–8023 สำหรับ audio chain

---

## 5. Logic ตามการตั้งค่า

### 5.1 ขั้น `audio_enhancement` (สรุป)

1. อ่าน `extracted_audio.wav`
2. ถ้า bypass ทั้งหมด (original + ไม่ denoise + ไม่ loudnorm) → copy ไฟล์ตรงๆ
3. มิฉะนั้นรัน FFmpeg chain:
   - `highpass=f=…` ถ้า `highpass_frequency_hz > 0`
   - `afftdn` ถ้า `denoise_model` ไม่ใช่ `off`
   - **loudnorm สองรอบ** (วัด JSON รอบแรก → encode `linear=true` รอบสอง) ถ้า `loudness_normalization_enabled`
4. **วัด peak (astats)** บน WAV หลัง chain — บันทึกเป็น `peak_sample_dbfs_pre_peak_force`
5. ถ้า `peak_force_to_window_enabled` และ peak **นอกช่วง** [-18, -14]:
   - คำนวณ gain (ดู [§7](#7-peak-window-และ-peak-force))
   - ใช้ `volume=…dB` (สูงสุด 3 รอบ)
   - วัด peak ใหม่ → `peak_sample_dbfs`
6. เขียน `enhanced_audio.wav` + metrics ลง `service_status`

**นโยบายเมื่อ FFmpeg ล้มเหลว:** copy `extracted_audio` เป็น enhanced + warning — pipeline ยังไปต่อได้

### 5.2 Profile `original`

- `loudness_normalization_enabled: false`
- MP4 มัก mux **เสียงจากวิดีโอต้นทาง** (`output_audio_source: source_video`)
- ยังอาจเปิด noise reduction / peak-force ถ้าส่ง partial config มา (แต่ไม่ผ่าน loudnorm ตาม profile)

### 5.3 Trim silence

- VAD บน `enhanced_audio` (หรือ fallback extracted ตาม `vad_audio_source`)
- `dead_air_cut_planning` สร้าง `keep_segments` ตัดช่วงที่เงียบเกิน `silence_threshold_seconds`
- Renderer ใช้ `smooth_crop_with_cuts` — ตัดทั้งภาพและเสียงให้ sync

> สมการและพารามิเตอร์ FFmpeg แบบละเอียดของ **ทุก feature** ดูที่ [§14](#14-logic-และสมการราย-feature-อ้างอิงโค้ด)

---

## 6. LUFS กับ peak dBFS (อ่านสองมิติให้เป็น)

### 6.1 เปรียบเทียบสั้นๆ

| | **LUFS** | **peak dBFS** |
|--|----------|----------------|
| ถามว่า | โดยรวม **ฟังรู้สึกดังแค่ไหน** | **จุดสูงสุด** ดังแค่ไหน |
| ลักษณะ | ค่าเฉลี่ยตามเวลา (มาตรฐาน EBU R128) | ค่าเดียว = sample สูงสุดทั้งไฟล์ |
| ในโปรเจกต์ | `loudnorm` + `target_lufs` | `astats` + ช่วง −18…−14 + peak-force |
| อ่านตัวเลข | ติดลบมาก = เงียบกว่า | **ใกล้ 0 = ดังกว่า**, ติดลบมาก = เงียบกว่า |

### 6.2 LUFS ลึกขึ้น

- **LUFS** (Loudness Units relative to Full Scale) ออกแบบให้ใกล้การรับรู้ของหู
- **Integrated loudness** (ค่า `I` ใน loudnorm) คือสิ่งที่เปรียบเทียบกับ `target_lufs`
- เป้าที่ใช้:
  - Podcast **-16 LUFS** — ทั่วไปสำหรับพอดแคสต์ / YouTube หลายแพลตฟอร์ม
  - Social **-14 LUFS** — ดังกว่า podcast เล็กน้อย (short-form)
  - Broadcast **-23 LUFS** — มาตรฐานกระจายเสียง มี headroom มากกว่า

**หลัง loudnorm คุณมักเห็น:**

- `input_lufs` → `output_lufs` ใกล้ `target_lufs`
- ไม่ได้การันตีว่า peak อยู่ใน −18…−14

### 6.3 peak dBFS ลึกขึ้น

- **dBFS** = เทียบกับ digital full scale (**0 dBFS** = ระดับสูงสุดที่ระบบรองรับโดยไม่ clip ในมิติดิจิทัล)
- **Peak** จาก `astats` = **Overall Peak level dB** ของไฟล์ (ไม่ใช่ RMS ไม่ใช่ LUFS)
- ช่วง **−18 … −14 dBFS** ในสเปกสถานีหมายถึง:
  - ต่ำกว่า **−18** → เงียบเกิน (peak ต่ำเกิน)
  - สูงกว่า **−14** → ดังเกิน (peak สูงเกิน)
  - อยู่ระหว่างสองค่านี้ → ผ่าน peak window

### 6.4 ทำไมต้องมีทั้งสองอย่าง

```text
         ┌─────────────────┐
         │    loudnorm     │  ← ดูแล “ฟังโดยรวม” (LUFS)
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │  astats (peak)  │  ← วัดยอดสูงสุด
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │  peak-force     │  ← ดูแล “ยอด peak” (dBFS)
         │  (volume)       │
         └─────────────────┘
```

**ตัวอย่างที่พบบ่อย:**

| หลัง loudnorm | LUFS | peak | ความหมาย |
|---------------|------|------|----------|
| โอเค | ใกล้ −16 | −50 | โดยรวมดังพอ แต่ยอด sample ต่ำมาก → peak-force ต้อง boost มาก |
| โอเค | ใกล้ −23 | −2.6 | โดยรวม broadcast-level แต่ยอดดังเกิน → peak-force ต้องลด |
| หลัง peak-force | อาจเพี้ยน | −14 | peak ผ่านสเปก แต่ LUFS ไม่ใช่เป้าเดิมแล้ว |

---

## 7. Peak window และ peak-force

### 7.1 ค่า default

| พารามิเตอร์ | Default |
|-------------|---------|
| `peak_level_window_low_dbfs` | **-18** |
| `peak_level_window_high_dbfs` | **-14** |
| `peak_window_report_enabled` | `true` (วัดและรายงานเสมอเมื่อ probe สำเร็จ) |
| `peak_force_to_window_enabled` | `false` (เปิดจาก UI toggle) |
| `peak_force_max_boost_db` | **0** (= ไม่จำกัด boost; ถ้าตั้งเป็นตัวเลขบวก = จำกัด boost สูงสุด) |

### 7.2 สูตร gain (แนวคิด)

ดูสูตรเต็มและตัวอย่างตัวเลขใน [§14.6](#146-peak-force-volume--สูตร-gain-ใน-python)

| สถานะ peak | การทำ |
|------------|--------|
| `peak > high` (−14) | **ลด** `gain = high - peak` (ไม่มีเพดาน attenuation) |
| `peak < low` (−18) | **เพิ่ม** ไปทางกลางช่วง `mid = (low+high)/2` → `gain = mid - peak` (จำกัดด้วย `max_boost_db` ถ้า > 0) |
| อยู่ในช่วงแล้ว | `gain = 0` |

**เป้ากลางช่วง (mid)** สำหรับ default = **(-18 + -14) / 2 = -16 dBFS**

### 7.3 หลายรอบ volume

- รันสูงสุด **3 รอบ** ถ้ายังนอกช่วงหลังแต่ละรอบ
- หลังเสร็จถ้ายังนอกช่วง → warning `AUDIO_PEAK_WINDOW_FORCE_INCOMPLETE`

### 7.4 Warning ที่เกี่ยวข้อง

| Code | ความหมาย |
|------|----------|
| `AUDIO_PEAK_MEASURE_FAILED` | astats วัด peak ไม่ได้ |
| `AUDIO_PEAK_FORCE_FAILED` | volume pass ล้มเหลว |
| `AUDIO_PEAK_WINDOW_FORCE_INCOMPLETE` | ยังนอกช่วงหลัง peak-force |
| `AUDIO_PEAK_WINDOW_FORCE_LUFS_DRIFT` | ปรับ peak แล้ว LUFS อาจไม่ตรง loudnorm เดิม |

---

## 8. สิ่งที่เห็นใน UI หลัง job เสร็จ

### 8.1 แผง Audio Output Insight

แสดงเมื่อ pipeline มี `audio_enhancement` และมี metrics

| ส่วน | เนื้อหา |
|------|---------|
| LUFS | input / output / target, delta เทียบเป้า |
| Peak ก่อน peak-force | `peak_sample_dbfs_pre_peak_force` — หลัง loudnorm ก่อน `volume` |
| Peak หลังปรับ | `peak_sample_dbfs` — ไฟล์ที่ mux (สอดคล้อง enhanced WAV) |
| Badge | อยู่ในช่วง / อยู่นอกช่วง (ปัดทศนิยม 3 ตำแหน่งเมื่อใกล้ขอบ) |
| บังคับปรับ peak | `peak_force_applied`, `peak_force_gain_db_total` |

### 8.2 Peak dBFS meter (แถบแนวนอน)

- แถบเขียว = ช่วง [-18, -14]
- จุดม่วง = ก่อน peak-force (ถ้าต่างจากหลังมากพอ)
- จุดส้ม = หลังปรับ (ไฟล์ mux)

### 8.3 Waveform คู่ (Enhanced + Extracted)

- **Enhanced WAV (หลัง chain)** — anchor ที่ peak หลังปรับ, เส้นช่วง −18/−14
- **Extracted WAV (ก่อน prep)** — anchor ที่ peak ก่อน prep (ถ้ามี), สเกลช่วงเดียวกันเพื่อเทียบ A/B

---

## 9. Waveform และเส้นอ้างอิง dBFS

### 9.1 ข้อมูลสองชั้น

| ชั้น | แหล่ง | ใช้ทำอะไร |
|------|--------|-----------|
| **ตัวเลข** | ffmpeg astats บนไฟล์ WAV | QC ว่า peak-force สำเร็จ, อยู่ในช่วง |
| **กราฟ** | Browser decode WAV → ~480 bars | ดูรูปร่างตามเวลา, เทียบก่อน/หลัง |

### 9.2 การแมปแนวตั้ง (สเกลช่วง)

เมื่อมี `referenceDbfsGuide`:

- ขอบบนของแถบช่วง ≈ **−14 dBFS** (เพดาน)
- ขอบล่างของแถบช่วง ≈ **−18 dBFS**
- แต่ละแท่ง: แปลงจาก amplitude สัมพัทธ์ → dBFS โดยใช้ `anchorDbfs` (peak จาก astats) แล้วแมปเข้าช่วง

**สูตรแนวคิด (frontend `audioDbfsGuide.ts`):**

```text
dbfs_bar = anchorDbfs + 20 × log10(peak_linear_bar)
display_position = map(dbfs_bar, low=-18, high=-14)
```

### 9.3 ทำไมคลื่นส่วนใหญ่อยู่ต่ำกว่าเส้น −18

**ปกติ** — เพราะ:

- **−14** คือ **ยอดสูงสุดทั้งไฟล์** (อาจเป็นจุดเดียวหรือช่วงสั้นมาก)
- คลื่นแสดง **ความดังรายช่วงเวลา** — พูดส่วนใหญ่เงียบกว่า peak มาก
- การ downsample เป็นแท่งอาจไม่โดนจุด peak สั้นมากทุกครั้ง

### 9.4 ความน่าเชื่อถือของกราฟ

| ถูกต้องสำหรับ | ไม่ใช่ |
|----------------|--------|
| รูปร่าง timeline, A/B ก่อน–หลัง prep | มิเตอร์ dBFS ทุก ms แบบสตูดิโอ |
| ยอดสูงสุดควรอยู่แถวเส้น −14 หลัง peak-force สำเร็จ | ทุกแท่งตรงกับ astats |

**แนะนำ:** ใช้ **ตัวเลข astats** เป็นหลักสำหรับ “เข้าช่วงไหม” — ใช้กราฟเป็นภาพประกอบ

---

## 10. Metrics และ warnings

### 10.1 Metrics หลักใน `audio_enhancement` step

| Key | ความหมาย |
|-----|----------|
| `input_lufs` / `output_lufs` | LUFS ก่อน/หลัง loudnorm |
| `target_lufs` | เป้าจาก profile |
| `loudnorm_two_pass` / `loudnorm_pass2_applied` | ใช้ two-pass หรือไม่ |
| `peak_sample_dbfs_pre_peak_force` | peak หลัง chain ก่อน volume |
| `peak_sample_dbfs` | peak หลัง peak-force (หรือเท่ากับ pre ถ้าไม่ force) |
| `peak_within_window` / `peak_within_window_pre_peak_force` | bool เทียบ [-18,-14] |
| `peak_level_window_low_dbfs` / `peak_level_window_high_dbfs` | ขอบช่วง |
| `peak_force_applied` | มีการรัน volume หรือไม่ |
| `peak_force_gain_db_total` | รวม gain (dB) ที่ใช้ |
| `peak_force_to_window_enabled` | ตั้งค่าเปิด force หรือไม่ |

### 10.2 Artifacts เสียง

| Artifact | คำอธิบาย |
|----------|----------|
| `extracted_audio.wav` | หลังดึงจากวิดีโอ |
| `enhanced_audio.wav` | หลัง enhancement (ไฟล์ที่วิเคราะห์ peak / waveform หลัก) |
| `vad_segments.json` | ช่วง speech/silence |
| `cut_plan.json` | ช่วงที่เก็บไว้หลังตัด dead air |

---

## 11. Config keys (API / manifest)

ส่งผ่าน `audio_enhancement` partial JSON ตอน `POST /jobs` หรือใน `service_config.audio_enhancement`:

| Key | ชนิด | หมายเหตุ |
|-----|------|----------|
| `denoise_model` | `off` \| `std` \| `leaky` | |
| `target_lufs` | number | เมื่อ loudnorm เปิด |
| `true_peak_db` | number | loudnorm TP |
| `loudness_range` | number | LRA |
| `highpass_frequency_hz` | number | 0 = ปิด |
| `loudness_normalization_enabled` | boolean | |
| `peak_level_window_low_dbfs` | number | default -18 |
| `peak_level_window_high_dbfs` | number | default -14 |
| `peak_window_report_enabled` | boolean | |
| `peak_force_to_window_enabled` | boolean | |
| `peak_force_max_boost_db` | number | 0 = uncapped boost |

Schema: `contracts/job_manifest.schema.json` → `service_config.audio_enhancement`

---

## 12. พจนานุกรมคำศัพท์

| คำ | ความหมายสั้นๆ |
|----|----------------|
| **dBFS** | Decibels relative to Full Scale — ใกล้ 0 ดังกว่า |
| **LUFS** | Loudness units (เฉลี่ยตามเวลา) — ใช้กับ loudnorm |
| **LRA** | Loudness range — ช่วง dynamic ของ loudnorm |
| **dBTP** | True peak — เป้า peak ของ loudnorm filter |
| **loudnorm** | FFmpeg filter มาตรฐาน EBU R128 |
| **astats** | FFmpeg filter สถิติ รวม Peak level dB |
| **peak-force** | ขั้น volume เพื่อเข้า peak window |
| **VAD** | Voice Activity Detection |
| **Dead air** | ช่วงเงียบยาวที่ตัดออก |
| **Mux** | รวมเสียงเข้า MP4 สุดท้าย |
| **enhanced_wav** | ใช้ `enhanced_audio.wav` เป็นแหล่งเสียง MP4 |

---

## 13. ตัวอย่างเคสจริง

### เคส A: เงียบมากหลัง loudnorm

| | ค่า |
|--|-----|
| ก่อน peak-force | **−50 dBFS** |
| หลัง peak-force (เปิด toggle) | **~−16 dBFS** (กลางช่วง) |
| gain รวม | **~+34 dB** |
| LUFS | อาจห่างจากเป้า profile |

**ความหมาย:** loudnorm ทำให้ “ฟังโดยรวม” โอเค แต่ยอด sample ยังต่ำ → peak-force boost มาก → อาจได้ noise ดังขึ้นด้วย

### เคส B: ดังเกินหลัง loudnorm

| | ค่า |
|--|-----|
| ก่อน peak-force | **−2.6 dBFS** |
| หลัง peak-force | **−14 dBFS** |
| การทำ | attenuate ~+11.4 dB |

**ความหมาย:** บน waveform เส้น “ก่อน” ควรอยู่เหนือแถบช่วง; หลังปรับยอดชิดเส้น −14 บน

### เคส C: ไม่เปิด peak-force

- มีแค่ตัวเลข peak รายงาน (ถ้า probe สำเร็จ)
- ไม่รัน `volume` — LUFS ยังใกล้เป้า profile มากที่สุด

---

## 14. Logic และสมการราย Feature (อ้างอิงโค้ด)

หัวข้อนี้สรุป **logic จริงใน repo** ว่าแต่ละฟีเจอร์ใช้ filter อะไร คำนวณอะไร สูตรเป็นแบบไหน — อ้างอิงหลักจาก `services/audio_enhancement/service.py`, `orchestrator/audio_profile.py`, `services/dead_air_cut_planning/service.py`, `frontend/src/lib/audioDbfsGuide.ts`, `frontend/src/lib/audioPeaks.ts`

### 14.0 ลำดับ filter ใน `audio_enhancement` (เมื่อไม่ bypass)

เมื่อ `loudness_normalization_enabled = true` ลำดับใน FFmpeg **คงที่**:

```text
[optional] highpass  →  [optional] afftdn  →  loudnorm  →  (หลัง encode) astats  →  (optional) volume
```

รวม filter ด้วย comma: `highpass=…,afftdn=…,loudnorm=…`  
ไฟล์อ้างอิง: `_pre_loudnorm_filter_parts()` แล้วต่อ `_loudnorm_pass1_token` / pass 2

**Bypass ทั้ง chain:** ถ้า `highpass_frequency_hz = 0` และ `denoise_model = off` และ `loudness_normalization_enabled = false` → copy `extracted_audio.wav` → `enhanced_audio.wav` โดยไม่ผ่าน FFmpeg filter

---

### 14.1 สไตล์เสียง MP4 (`audio_profile`) — ไม่ใช่สูตร แต่เป็นการ merge config

Orchestrator รวม config ตามลำดับ:

```text
template base  →  profile patch (_PROFILE_PATCHES)  →  partial จาก UI (JSON)
```

| Profile | พารามิเตอร์ที่ patch | ผลเชิง logic |
|---------|----------------------|--------------|
| `original` | `loudness_normalization_enabled: false`, denoise/highpass ปิด | ไม่รัน loudnorm ตาม profile |
| `podcast` | `target_lufs: -16`, `true_peak_db: -1.5`, `loudness_range: 11` | เป้า loudnorm แบบพอดแคสต์ |
| `social` | `target_lufs: -14`, LRA/TP เหมือน podcast | ดังกว่า podcast 2 dB (มิติ LUFS) |
| `broadcast` | `target_lufs: -23`, `loudness_range: 7` | เงียบกว่า + dynamic range แคบลง |

**ไม่มีสูตรคำนวณเพิ่มใน Python** — ค่าเหล่านี้ถูกส่งเข้า FFmpeg `loudnorm` โดยตรง (ดู §14.3)

---

### 14.2 High-pass (ตัดความถี่ต่ำ)

**เงื่อนไข:** `highpass_frequency_hz > 0`

**FFmpeg:**

```text
highpass=f={round(highpass_frequency_hz)}
```

**Logic:** กรองความถี่ต่ำกว่า cutoff (HVAC, rumble) ออกก่อน loudnorm/denoise  
**Default ใน service:** `80` Hz แต่ profile ส่วนใหญ่ตั้ง `0` = ปิด

---

### 14.3 Loudness normalization (`loudnorm`) — EBU R128 ผ่าน FFmpeg

#### พารามิเตอร์ที่ส่งเข้า filter

จาก config:

- `I` → `target_lufs` (integrated loudness เป้า, LUFS)
- `TP` → `true_peak_db` (true peak เป้า, dBTP — มัก **−1.5**)
- `LRA` → `loudness_range` (loudness range เป้า)

#### Pass 1 — วัด (encode ไป `null`)

```text
loudnorm=I={target_lufs}:TP={true_peak_db}:LRA={loudness_range}:print_format=json
```

FFmpeg พิมพ์ JSON ลง stderr มีฟิลด์เช่น `input_i`, `input_tp`, `input_lra`, `input_thresh`

#### Pass 2 — encode จริง (`linear=true`)

อ่านค่าวัดจาก pass 1 เป็น `(measured_I, measured_TP, measured_LRA, measured_thresh)` แล้วสร้าง:

```text
loudnorm=linear=true:
  I={target_lufs}:TP={true_peak_db}:
  LRA={LRA_pass2}:
  measured_I=...:measured_TP=...:measured_LRA=...:measured_thresh=...:
  print_format=json
```

โดย:

```text
LRA_pass2 = max(loudness_range_config, measured_LRA)
```

**เหตุผลในโค้ด:** ถ้า `LRA` เป้าต่ำกว่า LRA ที่วัดได้จากต้นทาง FFmpeg อาจไม่ใช้ linear mode ตามที่ต้องการ และ integrated loudness (`I`) อาจไม่ตามเป้า (พบบ่อยเมื่อ broadcast `LRA=7` กับซอร์ส dynamic กว้าง)

#### Fallback

| เหตุ | การทำ |
|------|--------|
| parse JSON pass 1 ไม่ครบ | single-pass ด้วย chain เดิม (pass1 token อย่างเดียว) |
| pass 2 encode ล้มเหลว | เหมือนกัน — single-pass |

#### สิ่งที่อ่านจาก metrics

จาก stderr JSON รอบสุดท้าย (ฟิลด์สุดท้ายที่ match):

- `input_lufs` ← `input_i`
- `output_lufs` ← `output_i`

**หมายเหตุ:** การ normalize ภายใน `loudnorm` เป็นอัลกอริทึมของ FFmpeg/EBU R128 — โปรเจกต์ไม่ได้ implement สูตร LUFS เอง แค่ส่งเป้า `I`, `TP`, `LRA`

#### ความสัมพันธ์ dB ทั่วไป (ใช้กับ `volume` ด้วย)

เมื่อต้องการเปลี่ยน amplitude แบบ linear จาก gain เป็น dB:

```text
amplitude_out = amplitude_in × 10^(gain_dB / 20)
```

---

### 14.4 Noise reduction (`afftdn`)

**เงื่อนไข:** `denoise_model !== "off"` (UI ส่ง `std` เมื่อเปิด toggle)

**FFmpeg ในโค้ดปัจจุบัน:**

```text
afftdn=nf=-25:nt=w
```

| พารามิเตอร์ | ค่า | ความหมายคร่าวๆ |
|-------------|-----|----------------|
| `nf` | −25 | noise floor (dB) สำหรับ FFT denoise |
| `nt` | `w` | noise type white |

**Logic:** ลดสเปกตรัม noise ในความถี่ — ไม่มีสูตร scalar แบบ “ลดกี่ dB” ใน Python; ผลขึ้นกับสัญญาณและ FFmpeg

---

### 14.5 วัด peak — `astats`

**หลัง** chain loudnorm (และก่อน `volume`):

```text
ffmpeg -af astats=metadata=1:reset=1 -f null -
```

**อ่านค่า:** บรรทัดสุดท้ายที่ match `Peak level dB: {ตัวเลข}` จาก stderr → `peak_sample_dbfs` หรือ `peak_sample_dbfs_pre_peak_force`

**นิยาม:** Overall peak ของไฟล์ในมิติ dBFS ตาม astats (ไม่ใช่ LUFS)

**เช็คอยู่ในช่วง (backend):**

```text
peak_within = (low_dbfs <= peak_dbfs <= high_dbfs)
```

default `low_dbfs = -18`, `high_dbfs = -14`

---

### 14.6 Peak-force (`volume`) — สูตร gain ใน Python

ฟังก์ชัน `_peak_window_gain_db(peak_dbfs, low, high, max_boost_db)`:

```text
mid = (low_dbfs + high_dbfs) / 2          # default mid = (-18 + -14) / 2 = -16

ถ้า peak_dbfs > high_dbfs:
    gain_dB = high_dbfs - peak_dbfs       # ลด (ค่า gain ติดลบ)

ถ้า peak_dbfs < low_dbfs:
    raw = mid - peak_dbfs                 # บวก (ค่า gain ติดบวก)
    ถ้า max_boost_db > 0:
        gain_dB = min(max_boost_db, raw)
    ถ้า max_boost_db == 0:
        gain_dB = raw                       # ไม่จำกัด boost (ค่า default ปัจจุบัน)

มิฉะนั้น:
    gain_dB = 0
```

**ตัวอย่างตัวเลข (default window):**

| peak ก่อน | เงื่อนไข | gain_dB | peak หลัง (โดยประมาณ) |
|-----------|----------|---------|----------------------|
| −2.6 | > high | −14 − (−2.6) = **−11.4** | ~−14 |
| −50 | < low | −16 − (−50) = **+34** | ~−16 (กลางช่วง) |
| −15 | ในช่วง | **0** | ไม่เปลี่ยน |

**นำ gain ไปใช้:**

```text
ffmpeg -af volume={gain_dB:.4f}dB
```

ซึ่งเทียบเท่า `amplitude × 10^(gain_dB/20)` สำหรับสัญญาณ

#### ลูป peak-force (สูงสุด 3 รอบ)

```text
ซ้ำสูงสุด 3 ครั้ง:
    ถ้า peak_within แล้ว → หยุด
    คำนวณ gain จาก peak ปัจจุบัน
    ถ้า |gain| < 1e-6 → หยุด
    ใช้ volume แล้ววัด astats ใหม่
    อัปเดต peak_within
```

`peak_force_gain_db_total` = ผลรวม gain ทุกรอบที่ใช้จริง

**หมายเหตุ:** หลัง peak-force อาจยังไม่เข้าช่วงพอดี (floating point / astats คลาด) → warning `AUDIO_PEAK_WINDOW_FORCE_INCOMPLETE`

---

### 14.7 UI — เช็ค “อยู่ในช่วง” และปัดทศนิยม

ใน `peakDbfsWithinWindowRounded` (frontend):

```text
p = round(peak, 3 decimals)
lo = round(low, 3)
hi = round(high, 3)
อยู่ในช่วง  ⟺  lo <= p <= hi
```

ทำให้กรณี peak จริง −13.9996 แต่แสดง −14.000 ยังถือว่า **อยู่ในช่วง** ตรงกับ badge

---

### 14.8 Waveform ใน UI — สมการแสดงผล

#### ขั้น 1: สร้าง envelope จาก WAV (`audioPeaks.ts`)

แบ่ง sample เป็น `barCount` บล็อก (default ~480):

```text
peak[i] = max(|sample|) ในบล็อก i
peak_normalized[i] = peak[i] / max(peak[ทั้งหมด])
```

→ ค่าสูงสุดในกราฟ = **1.0** (ยอด sample สูงสุดในไฟล์)

#### ขั้น 2: แปลงแท่ง → dBFS โดยใช้ anchor จาก astats

```text
dbfs_bar = anchorDbfs + 20 × log₁₀(max(peak_linear, 1e-6))
```

`anchorDbfs` = `peak_sample_dbfs` หลังปรับ (enhanced) หรือ `peak_pre` (extracted)

#### ขั้น 3: แมปแนวตั้งเทียบช่วง −18…−14

ให้ `lo = low_dbfs`, `hi = high_dbfs`, `span = hi - lo`:

**กรณี dbfs ≥ lo (อยู่ในหรือเหนือขอบล่างของช่วง):**

```text
t = min(1, (dbfs - lo) / span)
display_lin = 0.12 + 0.88 × t        # 0.12 ที่ขอบล่างช่วง, 1.0 ที่ hi
display_lin = min(1.12, display_lin)
```

**กรณี dbfs < lo (เงียบกว่าช่วง):**

```text
headroom = 22 dB
display_lin = 0.12 × max(0, (dbfs - (lo - headroom)) / headroom)
```

**ความสูงคลื่น (ครึ่งบน SVG):**

```text
y = mid - display_lin × amp
```

และใช้ `max(display_lin, peak_linear × 0.1)` เพื่อไม่ให้คลื่นหายเมื่อเงียบมาก

**เส้นอ้างอิงบนกราฟ:**

- `lo` → `display_lin` ≈ 0.12 (ขอบล่างแถบช่วง)
- `hi` → `display_lin` = 1.0 (ขอบบน = −14 dBFS เมื่อ anchor = post peak)

---

### 14.9 Trim long silence — `dead_air_cut_planning`

**Input:** `vad_segments.json` รายการ `{start, end, type: speech|silence}`

**พารามิเตอร์ default:**

| Key | Default |
|-----|---------|
| `silence_threshold_seconds` | 0.8 |
| `keep_padding_before` | 0.15 s |
| `keep_padding_after` | 0.2 s |
| `min_keep_segment_seconds` | 0.5 |

**Logic (สรุป):**

```text
1. ช่วง silence ที่ความยาว >= silence_threshold → ถือเป็น "ตัดได้"
2. ช่วงที่เหลือ = keep (พูด)
3. ขยาย keep ด้วย padding:
       start' = max(0, start - keep_padding_before)
       end'   = min(duration, end + keep_padding_after)
4. รวม keep ที่ซ้อนทับ, ทิ้ง keep ที่สั้นกว่า min_keep_segment_seconds
```

**ไม่มีสูตร dB** — เป็น logic เวลา (วินาที) ล้วนๆ

**VAD (Silero):** โมเดล ONNX แยก speech/silence — ไม่ได้กำหนด threshold dB ใน Python ของ dead_air; threshold อยู่ที่โมเดล + การรวมช่วง

---

### 14.10 `audio_extraction` (ดึงเสียง)

FFmpeg decode จากวิดีโอ → mono PCM WAV (default **48 kHz**, 16-bit)  
**ไม่มีการปรับระดับเสียง** ในขั้นนี้ — เป็นไฟล์ดิบสำหรับขั้นถัดไป

---

### 14.11 สรุปตาราง: Feature → เครื่องมือ → สูตร/Logic

| Feature | เครื่องมือ | Logic / สูตรหลัก |
|---------|-----------|------------------|
| สไตล์ LUFS | `loudnorm` | เป้า `I=target_lufs`, `TP`, `LRA`; 2-pass linear |
| Noise reduction | `afftdn` | `nf=-25, nt=w` (FFT denoise) |
| High-pass | `highpass` | cutoff = `highpass_frequency_hz` |
| รายงาน peak | `astats` | อ่าน `Peak level dB` |
| Peak-force | `volume` | `gain = f(peak, -18, -14, mid=-16)`; `×10^(gain/20)` |
| Waveform UI | Web Audio + JS | `dbfs = anchor + 20log₁₀(p)`; แมปสู่ช่วง |
| Trim silence | Silero + planner | `silence_duration ≥ threshold` → ตัด |
| Mux MP4 | `ffmpeg_renderer` | ใช้ `enhanced_audio` หรือ `source_video` |

---

## 15. ข้อจำกัดที่ควรรู้

1. **LUFS ≠ peak** — ปรับอย่างหนึ่งไม่ได้แปลว่าอีกอย่างจะผ่านสเปก
2. **peak-force หลัง loudnorm** อาจทำให้ LUFS เพี้ยน — โดย design
3. **Waveform ใน UI** เป็นภาพประกอบ — ไม่แทนมิเตอร์ QC ระดับสถานี
4. **QC สถานี strict** ควรใช้มิเตอร์ภายนอก (true peak / LUFS) เสริม
5. **Job เก่า** ก่อน deploy logic ใหม่ (เช่น cap +12 dB) ต้อง **รัน job ใหม่** หลัง restart `audio_enhancement` worker
6. **Frontend dev** — ถ้า Internal Server Error หลัง `npm run build` ขณะ `dev` รันอยู่ ให้ลบ `frontend/.next` แล้ว restart dev

---

## การรัน local stack (อ้างอิง)

```bash
./scripts/start_local_stack.sh --detach
cd frontend && npm run dev
# http://localhost:3000
```

Orchestrator: `http://localhost:8000` · `audio_enhancement`: พอร์ต **8022**

---

*อัปเดตตามโค้ดใน repo — ถ้า behavior เปลี่ยนใน `services/audio_enhancement/service.py` หรือ UI ให้แก้เอกสารนี้คู่กัน*
