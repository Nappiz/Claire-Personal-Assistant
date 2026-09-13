# Backend verification

Run the suite from the repository root:

```powershell
.\backend\venv\Scripts\python.exe backend\scripts\run_tests.py
```

The runner supplies temporary SQLite/Qdrant paths and rejects real network
connections. Windows asyncio socketpairs remain enabled. It never starts the
FastAPI lifespan, schema backfill, vector reindex, or production workers.

Optional test patterns can be passed as positional arguments. Results are also
saved in the ignored `backend/.refactor/test-results.json`.

The OpenAPI fixture in `tests/fixtures/api_openapi.json` was recorded before
router extraction. Do not regenerate it to conceal a refactor regression.

Baseline before extraction: **163 tests, all passed** (161 existing tests and
two API/SSE contract tests). Initial runner-only failures in logging, asyncio
socketpair isolation, fixture chunk placement, and Windows resource cleanup
were corrected before application extraction.
