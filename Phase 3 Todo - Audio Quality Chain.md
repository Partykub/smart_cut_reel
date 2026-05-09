# Phase 3 Todo - Audio Quality Chain

**Status:** ✅ DONE (Phase 3.A → 3.E core path) — pipeline `phase3_audio_quality_cut` (14 steps) ใช้งานได้จริง: Silero VAD v5 + ffmpeg denoise/loudnorm + faster-whisper word timestamps + filler-word cut. Phase 1/2 ยัง backward-compatible. ขั้นถัดไปที่ยังไม่ทำ: speaker diarization (3.F) และ mastering chain (3.G)

**Goal:** ยกระดับคุณภาพเสียงของ pipeline จาก MVP (energy VAD + raw audio) ขึ้นไปสู่ระดับ "production podcast" — ใส่ AI VAD, audio enhancement (denoise + LUFS normalize), ASR + word-level filler-word cut, และเปิดทาง diarization/mastering chain ใน phase ย่อยถัดไป  
**Scope:** ขยาย Phase 2 (`Phase 2 Todo - Dead Air Cutting.md`) เพิ่ม service ใหม่ 2 ตัว (`audio_enhancement`, `transcription`) + swap VAD backend จาก energy → Silero v5 + เปิด toggle ตัด filler words. **ไม่ใช่** speaker diarization เต็มสูตร, ไม่ใช่ EQ/compression chain ครบ studio, ไม่ใช่ LLM editor, ไม่ใช่ multi-cam.

> Phase 1 และ Phase 2 ต้อง stable ก่อน — Phase 3 *ขยาย* pipeline ของ Phase 2 ไม่ทดแทน

## 1. Phase 3 Output ที่ต้องได้

ผู้ใช้สามารถ:

1. Upload วิดีโอ + เลือก pipeline `phase3_audio_quality_cut`
2. เปิด/ปิด feature `enhance_audio` (denoise + loudness normalize)
3. เปิด/ปิด feature `remove_filler_words` (ตัด "เอ่อ", "อืม", "อ่า", "um", "uhh")
4. ระบบ extract เสียง → enhance → Silero VAD → transcribe → cut plan (silence + filler) → render
5. ดาวน์โหลด artifact ใหม่: `enhanced_audio.wav`, `transcript.json` ได้
6. เห็น metric ใหม่ใน dashboard: `total_filler_seconds_removed`, `loudness_in_lufs`, `noise_reduction_db`

## 2. Stack สำหรับ Phase 3

```text
Debug Frontend
  -> Orchestrator API
      -> MinIO
      -> Validation Service
      -> Media Metadata Service
      -> Audio Extraction Service
      -> Audio Enhancement Service           (new — denoise + LUFS normalize)
      -> Voice Activity Detection Service    (Silero VAD v5 backend)
      -> Transcription Service               (new — faster-whisper word timestamps)
      -> Dead Air Cut Planning Service       (extended — เพิ่ม filler word cut)
      -> Proxy/Frame Sampling Service
      -> Body Detection Service
      -> Track Interpolation Service
      -> Reframe Planning Service
      -> Easing/Smoothing Service
      -> Render Plan Compiler Service
      -> FFmpeg Renderer Service
```

หลักคิด:

- **Audio enhancement ทำก่อน VAD/ASR** เพราะ denoise + level normalize boost accuracy ของ tier ถัดไปได้ 10-30%
- **Silero VAD ทดแทน energy backend** เป็น default ของ Phase 3 — backend `energy` ยังอยู่สำหรับ debug หรือ fallback
- **Transcription รันหลัง VAD** เพื่อใช้ speech segment เป็น hint ลด computation (ไม่ ASR ทุก ms ของ silence)
- **Cut Plan รวมจาก 2 source**: VAD silence threshold + ASR filler word matches

## 3. MinIO Layout เพิ่มเติม

```text
jobs/{job_id}/
  artifacts/
    extracted_audio.wav
    enhanced_audio.wav                       (new — Phase 3)
    vad_segments.json
    transcript.json                          (new — Phase 3)
    cut_plan.json
    ...
  logs/
    audio_enhancement.log                    (new)
    transcription.log                        (new)
```

## 4. Service Todo

### S-15: Audio Enhancement Service (NEW)

**Purpose:** ทำ denoise + loudness normalize เพื่อให้ VAD/ASR ทำงานบน input ที่สะอาด

Todo:

- รับ `extracted_audio.wav` จาก `audio_extraction`
- รัน ffmpeg pipeline:
  - `arnndn=m=<rnnoise_model>` (RNNoise denoise — มากับ ffmpeg, ไม่ต้อง dep เพิ่ม)
  - `loudnorm=I=-16:TP=-1.5:LRA=11` (EBU R128 normalize เป็น -16 LUFS, peak -1.5 dBTP)
  - `highpass=f=80` ตัด rumble/HVAC
- เขียน `artifacts/enhanced_audio.wav` (mono 16 kHz pcm_s16le)
- ใส่ metric ลง output (input/output LUFS, noise_reduction_db estimate)

Config (job_manifest.service_config.audio_enhancement):

```json
{
  "denoise_model": "std",
  "target_lufs": -16.0,
  "true_peak_db": -1.5,
  "loudness_range": 11.0,
  "highpass_frequency_hz": 80
}
```

**Failure policy:** `warn_then_passthrough` — ถ้า ffmpeg fail ให้ fallback ใช้ `extracted_audio.wav` ตรง ๆ + emit warning, ไม่ fail job

Done when:

- output WAV ผ่าน LUFS measurement ใกล้ target ±1 LUFS
- duration เท่าเดิม (±10ms tolerance)
- VAD บน enhanced audio ได้ผลดีกว่า raw audio บน clip ทดสอบที่มี noise

---

### S-13b: Voice Activity Detection — Silero v5 backend (UPDATED)

**Purpose:** swap default backend จาก `energy` → `silero_v4` (จริง ๆ คือ Silero VAD v5 model — ใช้ ID เดิมเพื่อ backward compat)

Todo:

- เพิ่ม dependency: `silero-vad>=5,<6` + `onnxruntime>=1.16,<2`
- Implement branch `model == "silero_v4"` ที่เปิด slot ไว้แล้วใน `services/voice_activity_detection/service.py`
- ใช้ `silero_vad.get_speech_timestamps()` ที่คืน chunk บน sample-level → แปลงเป็น `segments[]` schema เดิม
- รับ input จาก `enhanced_audio.wav` (ถ้ามี) ก่อน fallback `extracted_audio.wav`
- เก็บ confidence ต่อ chunk ใน segment payload

Config (เพิ่ม):

```json
{
  "model": "silero_v4",
  "speech_threshold": 0.5,
  "min_speech_duration_seconds": 0.25,
  "min_silence_duration_seconds": 0.2,
  "speech_pad_seconds": 0.05,
  "audio_source": "enhanced_audio_or_extracted"
}
```

**Failure policy:** `fail_job` (Silero โหลดไม่ได้ → fail; energy backend ยังเป็น manual fallback ผ่าน config)

Done when:

- segments cover full duration เหมือน energy backend
- accuracy บน clip ทดสอบ noisy ดีกว่า energy ≥ 20%
- existing tests ของ energy backend ยัง pass

---

### S-16: Transcription Service (NEW)

**Purpose:** ทำ ASR ด้วย faster-whisper ได้ word-level timestamps สำหรับตัด filler words

Todo:

- เพิ่ม dependency: `faster-whisper>=1,<2` (pulls CTranslate2)
- รับ `enhanced_audio.wav` (หรือ `extracted_audio.wav` fallback) + `vad_segments.json`
- โหลด model ตาม config (`tiny`, `base`, `small`, `medium`) — default `small` (~250 MB) สำหรับ Thai/multi-lingual
- รันเฉพาะช่วง `speech` segments จาก VAD เพื่อ skip silence (ลด compute เยอะ)
- เปิด `word_timestamps=True` ของ faster-whisper
- เขียน `artifacts/transcript.json`:

```json
{
  "schema_version": "3.0.0",
  "job_id": "...",
  "model": "small",
  "language": "th",
  "segments": [
    {
      "start": 1.85, "end": 4.2,
      "text": "สวัสดีครับ เอ่อ วันนี้เรา...",
      "words": [
        { "word": "สวัสดี",  "start": 1.85, "end": 2.3, "confidence": 0.94 },
        { "word": "ครับ",    "start": 2.3,  "end": 2.6, "confidence": 0.91 },
        { "word": "เอ่อ",    "start": 2.7,  "end": 2.95, "confidence": 0.62, "is_filler": true },
        ...
      ]
    }
  ],
  "metrics": {
    "total_words": 234,
    "filler_word_count": 12,
    "average_confidence": 0.87
  }
}
```

Config (job_manifest.service_config.transcription):

```json
{
  "model": "small",
  "language": "auto",
  "compute_type": "int8",
  "filler_words_th": ["เอ่อ", "อืม", "อ่า", "อ่ะ", "เอ้อ"],
  "filler_words_en": ["um", "uhh", "ah", "er", "like"],
  "filler_min_silence_around_seconds": 0.05
}
```

Filler detection rule: word match (case-insensitive) ที่อยู่กึ่งกลาง utterance + มี silence ≥ 0.05s รอบ ๆ → mark `is_filler: true`

**Failure policy:** `warn_then_skip_filler_cut` — ถ้า ASR fail ให้ pipeline ผ่านได้ แต่ปิด filler word cut อัตโนมัติ + warning

Done when:

- transcript.json schema validate ได้
- run บน clip ทดสอบ 10s ภาษาไทย → text สมเหตุสมผล + word_timestamps ครบ
- ลง model 1 ครั้ง (cache `~/.cache/huggingface` หรือ working dir) ใช้ซ้ำได้

---

### S-14b: Dead Air Cut Planning — Filler Word Cut (EXTENDED)

**Purpose:** ขยาย service เดิมให้ตัดทั้ง silence (จาก VAD) + filler words (จาก transcript)

Todo:

- รับ artifact เพิ่ม: `transcript.json` (optional ถ้า remove_filler_words = true)
- ขยาย algorithm:
  1. เริ่มจาก keep_segments เดิม (จาก VAD silence threshold)
  2. ถ้า `remove_filler_words` = true:
     - หา word ที่ `is_filler = true` ใน transcript
     - กำหนด cut window = [word.start - 0.05, word.end + 0.05]
     - ลบ window นั้นออกจาก keep_segments (ตัดออกตรงกลาง keep segment ได้ถ้าจำเป็น)
  3. apply min_keep_segment_seconds เหมือนเดิม
- ขยาย `metrics`:

```json
{
  "total_kept_seconds": 95.4,
  "total_removed_seconds": 24.6,
  "removed_silence_seconds": 18.2,
  "removed_filler_seconds": 6.4,
  "filler_word_count": 12,
  "cut_count": 45,
  "compression_ratio": 0.795
}
```

Config (เพิ่มใน dead_air_cut_planning):

```json
{
  "filler_padding_before": 0.05,
  "filler_padding_after": 0.05,
  "merge_adjacent_cuts_within_seconds": 0.1
}
```

Done when:

- ตัดเฉพาะ silence (เหมือน Phase 2) ได้เหมือนเดิม
- ตัด silence + filler word ทดสอบ clip 30s ภาษาไทยที่มี "เอ่อ" 5 ครั้ง → output sonic ฟังธรรมชาติ
- existing Phase 2 tests ยัง pass

---

## 5. Contracts Bump

### 5.1 schema_version → `3.0.0`

- `job_manifest.schema.json`: เพิ่ม `phase3_audio_quality_cut` ใน `pipeline_id` enum + `enhanced_audio` artifact + service_config blocks ใหม่
- `artifact_manifest.schema.json`: เพิ่ม `enhancedAudioArtifact`, `transcriptArtifact`
- `service_status.schema.json`: เพิ่ม `audio_enhancement`, `transcription` ใน step enum + `phase3Steps` (14 steps)

### 5.2 New `pipeline_id`: `phase3_audio_quality_cut`

```json
{
  "pipeline_id": "phase3_audio_quality_cut",
  "steps": [
    "validation",
    "media_metadata",
    "audio_extraction",
    "audio_enhancement",
    "voice_activity_detection",
    "transcription",
    "dead_air_cut_planning",
    "proxy_frame_sampling",
    "body_detection",
    "track_interpolation",
    "reframe_planning",
    "easing_smoothing",
    "render_plan_compiler",
    "ffmpeg_renderer"
  ]
}
```

(14 steps; Phase 1 = 9, Phase 2 = 12, Phase 3 = 14)

### 5.3 New `enabled_features`

```json
"enabled_features": {
  "remove_dead_air": true,
  "enhance_audio": true,
  "remove_filler_words": true
}
```

### 5.4 ports ใน start_local_stack.sh

- `8022` — audio_enhancement
- `8023` — transcription

## 6. Acceptance Criteria

### Quality
- ผู้ใช้อัพ podcast 60s ที่มี HVAC noise + filler words 5-10 คำ → output:
  - ความเงียบยาวถูกตัด ≥ 80% (เหมือน Phase 2)
  - filler words ≥ 70% หายไป (จาก ASR detection)
  - audio LUFS ใกล้ -16 ±1 dB
  - subjective listening test ฟังชัดเจนขึ้น noise floor ลด
- VAD บน clip noisy: F1 ≥ 0.9 (เทียบ energy F1 ~0.7)

### Engineering
- Phase 1 + Phase 2 jobs ยังทำงานเหมือนเดิม (no regression)
- ทุก service ใหม่ทดสอบแยกได้ผ่าน FastAPI TestClient
- e2e test สร้าง clip มี HVAC noise + "uhh" 3 ครั้ง → output trim ตรงกับ cut_plan
- Full pipeline 60s clip → จบใน <8 นาที CPU บน M-series

### Operational
- `./scripts/start_local_stack.sh --detach` start 14 services + orchestrator ขึ้นโดยไม่ error
- frontend toggle "Enhance audio" + "Remove filler words" ทำงานถูก
- model weight ของ Silero และ Whisper auto-download/cache ครั้งแรก

## 7. Parallel Todo Board

ติ๊ก `[x]` เมื่อเสร็จ ลำดับ ID ต่อจาก Phase 2 ตาม lane เดิม + lane ใหม่ M (audio enhancement), N (transcription)

### A — Orchestrator / Contracts

- [x] P3-A01: Bump `job_manifest.schema.json` → `schema_version 3.0.0`, เพิ่ม `phase3_audio_quality_cut` pipeline_id, เพิ่ม `enabled_features.enhance_audio` + `remove_filler_words`, เพิ่ม service_config blocks: `audio_enhancement`, `transcription`, ขยาย `dead_air_cut_planning` config
- [x] P3-A02: ขยาย `artifact_manifest.schema.json` → เพิ่ม `enhanced_audio`, `transcript`
- [x] P3-A03: ขยาย `service_status.schema.json` → เพิ่ม step `audio_enhancement`, `transcription` + `phase3Steps` (14 steps)
- [x] P3-A04: ขยาย `path_resolver.py` รู้จัก artifact ใหม่ 2 ตัว + `contracts.py` PHASE_3_PIPELINE_ID, PHASE_3_STEP_IDS, PIPELINE_STEPS_BY_ID, ARTIFACT_PRODUCERS, ARTIFACT_CONTENT_TYPES
- [x] P3-A05: ขยาย `OrchestratorService` รองรับ pipeline_id phase3 + load template ใหม่ + `manifest_manager.create_initial_job_state` รองรับ 14 steps (เปลี่ยนชื่อ pipeline_id ให้สอดคล้อง: ใช้ดิสคริมิเนเตอร์ `oneOf` ใน schema เพื่อไม่กระทบ Phase 1/2)
- [x] P3-A06: เพิ่ม env `ORCHESTRATOR_SERVICE_ENDPOINTS` 2 entries ใหม่ + `scripts/start_local_stack.sh` start ports 8022/8023

### M — Audio Enhancement

- [x] P3-M01: skeleton `services/audio_enhancement/` (FastAPI `/run` + service.py + tests/__init__.py)
- [x] P3-M02: implement ffmpeg `highpass` + `afftdn` denoise + `loudnorm` filter chain → `enhanced_audio.wav` (ใช้ filter ที่มากับ ffmpeg ตรง ๆ ไม่ต้อง model file เพิ่มเติม)
- [x] P3-M03: emit metrics (sample_rate, channels, target/measured LUFS, denoise_model) + warning policy `warn_then_passthrough` ผ่าน `AUDIO_ENHANCEMENT_FALLBACK`

### K — Voice Activity Detection (Silero swap)

- [x] P3-K01: เพิ่ม `silero-vad>=5,<6` + `onnxruntime>=1.16,<2` ลง requirements.txt
- [x] P3-K02: implement Silero v5 backend ใน `voice_activity_detection/service.py` (branch `model == "silero_v4"`) — โหลด model 1 ครั้งต่อ process ผ่าน `_load_silero_model()` lock + cache, ใช้ `get_speech_timestamps`
- [x] P3-K03: รับ `audio_source` config (`enhanced_audio` / `extracted_audio` / `enhanced_audio_or_extracted`) — fallback enhanced → extracted ถ้าไม่มีตัวแรก + tests ครอบคลุม

### N — Transcription

- [x] P3-N01: เพิ่ม `faster-whisper>=1,<2` + `numpy` ลง requirements.txt + skeleton `services/transcription/`
- [x] P3-N02: implement faster-whisper transcription with word_timestamps + อ่าน vad_segments เพื่อรันเฉพาะช่วง speech (skip silence)
- [x] P3-N03: filler word detection — match dictionary (Thai + English defaults) + check silence padding around word → `is_filler: true`
- [x] P3-N04: cache management — โหลด whisper model lazy ครั้งแรกผ่าน `_load_faster_whisper_model()` lock + cache ต่อ process; ทดสอบด้วย mock WhisperModel

### L — Dead Air Cut Planning (extend)

- [x] P3-L01: รับ `transcript.json` artifact (optional) + ขยาย algorithm ตัด filler words ออกจาก keep_segments (split keep segment ได้ถ้า filler อยู่ตรงกลาง)
- [x] P3-L02: ขยาย metrics: `removed_silence_seconds`, `removed_filler_seconds`, `filler_word_count` + tests รวม Phase 2 backward-compat

### B — Frontend

- [x] P3-B01: extend `lib/types.ts` — เพิ่ม StepName ใหม่, PHASE_3_STEP_ORDER, EnabledFeatures fields, Transcript types
- [x] P3-B02: UploadForm — toggle "Enhance audio" + "Cut filler words" + auto switch pipeline_id (ตามตารางผสม)
- [x] P3-B03: StatusBoard render 14 step + badge `quality` สำหรับ `audio_enhancement` + `transcription`
- [x] P3-B04: TranscriptCard component แสดง word + highlight filler word + `/api/jobs/[jobId]/artifacts/transcript` route ใช้ artifact proxy เดิม

### I — Integration / QA

- [x] P3-I01: e2e test (`tests/integration/test_phase3_audio_quality_e2e.py`) — synthetic 9s clip → audio extraction → audio enhancement (real ffmpeg) → Silero VAD → transcription (mock model) → dead-air planning + filler cut
- [x] P3-I02: orchestrator + service unit/integration tests ครบ — 91 test ผ่านทั้งหมด (74 unit + 17 integration)
- [x] P3-I03: live stack smoke — บูต 14 service + orchestrator port 8000-8023 ผ่าน `start_local_stack.sh --detach`; create job ด้วย pipeline_id ทั้ง 3 phase ผ่านทั้งหมด

## 8. Dependency กลางของ Phase 3

- P3-A01 unblock contract bump ทุกคน
- P3-K01 (deps) unblock P3-K02 และ P3-N01
- P3-M02 ต้องเสร็จก่อน P3-K03 (VAD รับ enhanced_audio)
- P3-K02 ต้องเสร็จก่อน P3-N02 (transcription skip silence ตาม VAD)
- P3-N03 ต้องเสร็จก่อน P3-L01 (filler cut ใน planning)
- P3-A06 ต้องเสร็จก่อน P3-I02 (full stack integration)
- P3-L02 ต้องเสร็จก่อน P3-I03 (e2e ตรวจ filler removal)

## 9. งานที่เริ่มได้ทันที (เมื่อกด start Phase 3)

- Orchestrator: P3-A01 (contract bump) — unblock ทุกคน
- Audio enhancement team: P3-M01 skeleton (mock manifest)
- Audio AI team: P3-K01 dep + P3-K02 Silero implementation
- Frontend: P3-B01 types + UI wireframe
- QA: P3-I01 fixtures (จาก schema draft)

## 10. ไม่ทำใน Phase 3 (ไว้ Phase ถัดไป)

- Speaker diarization (pyannote 3.1) — Phase 3.F (option, เฉพาะ podcast หลายผู้พูด)
- Mastering chain เต็ม (EQ + compressor + de-esser + limiter) — Phase 3.G
- LLM editor (ใช้ Claude/GPT อ่าน transcript ตัดประโยคซ้ำ/ออกนอกเรื่อง) — Phase 4
- Highlight detection / auto reels picker — Phase 4
- Music ducking, BGM mixing — Phase 4

---

## ภาคผนวก: Tier vs Phase Mapping

| Tier ที่อธิบายในเอกสารคุยกัน | Phase ปฏิบัติ |
|------------------------------|---------------|
| Tier 1 — Silero VAD            | P3-K (Phase 3 Section K) |
| Tier 4 — Audio Enhancement     | P3-M (denoise + LUFS)    |
| Tier 2 — ASR + filler word cut | P3-N + P3-L              |
| Tier 8 — Audio Mastering       | Phase 3.G (deferred)      |
| Tier 3 — Speaker Diarization   | Phase 3.F (deferred)      |
| LLM editor                     | Phase 4 (R&D)             |
