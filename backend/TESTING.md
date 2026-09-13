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

Architecture and extraction checks (parse source only):

```powershell
.\backend\venv\Scripts\python.exe backend\scripts\check_architecture.py --baseline-ref refactor-backend-baseline
.\backend\venv\Scripts\python.exe backend\scripts\verify_extraction.py
```

The graph golden fixture was captured from the original Git baseline using a
deterministic recording driver. It verifies ordered Cypher, parameters, results,
and transaction count. These fixtures do not replace a live Neo4j integration
suite; the stage-0â€“4 refactor is verified offline without altering local stores.
