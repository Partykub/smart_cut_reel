# Hyperframes Finishing Service

Standalone finishing service for upload -> template routing -> Hyperframes render -> download.

## Current Status

- Python API and job orchestration skeleton are implemented in this repo.
- The default render path now uses a real Hyperframes CLI executor that generates a per-job composition project and renders MP4 output.
- A mock executor still exists for narrow unit tests and can be forced with `SMART_CUT_HYPERFRAMES_RENDERER=mock`.
- The Hyperframes runtime scaffold lives under `services/hyperframes_finishing/hyperframes/`.

## Local Run Notes

- API entrypoint: `services/hyperframes_finishing/api.py`
- Storage root env: `SMART_CUT_HYPERFRAMES_ROOT`
- Fallback storage root: `SMART_CUT_OBJECT_STORE_ROOT/hyperframes-finishing`

### Suggested local commands

```bash
# Python API
.venv/bin/python -m uvicorn services.hyperframes_finishing.api:create_app --factory --reload --port 8050

# Worker loop (single pass example)
.venv/bin/python - <<'PY'
from services.hyperframes_finishing.worker import process_queued_jobs_once
print(process_queued_jobs_once())
PY

# Frontend
cd frontend && npm run dev

# Targeted tests
.venv/bin/python -m unittest -v \
	services.hyperframes_finishing.tests.test_hyperframes_finishing_service \
	services.hyperframes_finishing.tests.test_hyperframes_finishing_api \
	services.hyperframes_finishing.tests.test_template_router \
	services.hyperframes_finishing.tests.test_worker \
	services.hyperframes_finishing.tests.test_rendering
```

## Runtime Notes

- The real executor shells out to `npx hyperframes render` from `services/hyperframes_finishing/hyperframes/`.
- Local rendering requires Node, `npx`, `ffmpeg`, and enough free RAM for Chromium-based rendering.
- Current hardening gaps are richer subtitle styling, deeper asset validation, and operational limits/timeouts.
