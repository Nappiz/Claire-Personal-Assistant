# AI/RAG regression evaluation

Run from the repository root:

```powershell
.\backend\venv\Scripts\python.exe backend\scripts\run_evals.py
```

manifest.json versions the evaluation selection, not the production prompt.
Six independent groups require 100% fixture fidelity and zero skipped cases.
The runner checks missing/duplicate selections and writes ignored
.refactor/eval-results.json. Failure returns a nonzero exit code.

| Group | Evidence |
| --- | --- |
| Prompt requests | Frozen SHA-256 request digests; temporal context with fixed clock |
| Answer/tool loop | First delta before provider completion, verbatim whitespace, fragmented tool replay metadata, search/read ordering, bounded recovery and stream cancellation |
| Retrieval | Deterministic vector payload/ranking fixtures, project/global scope, URL filtering and TF-IDF |
| Graph facts | Frozen ordered Cypher/parameters/results, identity/provenance, residence and fact policies |
| Failure safety | Partial write, lost lease, duplicate claim, cancellation and worker shutdown |
| HTTP/SSE smoke | Isolated SQLite + fake provider through real routers, published OpenAPI and terminal SSE |

Result at the stage-5â€“8 checkpoint: 82/82 cases; every group fidelity=1.0.
This measures **contract regression**, not real-model factuality or production
answer quality. Live answer quality is explicitly reported as not_evaluated.
Do not advertise fixture pass rate as a human/LLM quality score.

Before a future prompt/model/retrieval change, use a separate authorized task
to add representative labelled queries, expected source IDs/facts, independent
reference answers, recall@k/MRR and answer-grounding criteria. Compare against a
pinned model/prompt/index version, control provider cost and private-data use,
and attach evaluation evidence before release. Never regenerate these
characterization fixtures to approve a structural refactor.
