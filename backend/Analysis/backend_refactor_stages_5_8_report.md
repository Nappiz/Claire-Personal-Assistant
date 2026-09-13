# Laporan refactor backend tahap 5â€“8

Tanggal: 13 September 2026. Branch: `codex/backend-stages-5-8`.
Checkpoint sebelum pekerjaan: `33f5356` / `refactor-stages-0-4-complete`.
Aturan wajib: REFACTORING_RULES.md dan enterprise_backend_refactor_plan.md.

## Status yang sebenarnya

| Tahap | Hasil |
| --- | --- |
| 5 â€” LLM pipeline | Selesai: policy deterministik, gateway provider, response normalization, workflow terinjeksi |
| 6 â€” Memory orchestration | Selesai: scope/read, turn/persistence, outbox/write, summary/title/reindex dipisah per capability |
| 7 â€” Worker/bootstrap | Selesai: worker terinjeksi, bootstrap kecil, cancellation dikuras saat shutdown |
| 8 â€” Hardening | Gate runtime, CI, eval offline, telemetry dan penghapusan facade tanpa consumer selesai |
| 8 â€” Retirement seluruh facade | **Belum selesai:** sebagian tes legacy dan audit/tools masih mengimpor facade; tidak dihapus sebelum consumer migrasi |

Jadi runtime baru sudah bermigrasi sampai hardening tahap terakhir, tetapi jangan
menganggap seluruh compatibility debt telah hilang. Daftar owner/kriteria
penghapusan ada di services/README.md; review berikutnya 1 Oktober 2026.

## Scope dan kontrak

Hanya backend. Tidak mengubah frontend, ORM/schema, migration, konfigurasi atau
dependency provider. Tidak menjalankan lifespan, schema repair, wipe, reindex,
migration, atau provider live terhadap data pengguna.

Kontrak yang dipertahankan:

- URL/method/status/payload API dan framing/urutan/termination SSE.
- Prompt dan tool schema, model/provider/fallback, timeout, retry, token accounting.
- Scope/ranking/embedding signature/point ID/payload vector dan Cypher/provenance graph.
- Begin turn, atomic persistence, durable outbox, lease token/expiry, retry/cancel,
  partial write, tombstone dan compensation; summary optimistic compare-and-swap.
- Interval worker 3600/60/60 detik, limit outbox 25 dan summary 20, reindex sebelum warmup.

Perubahan shutdown yang eksplisit: cancellation sekarang berada dalam finally dan
di-await melalui gather. Ini menguras coroutine, bukan memaksa menghentikan fungsi
yang sudah berjalan dalam executor thread; lease/deletion guards tetap berlaku.

## Pemindahan dan ownership

| Asal | Owner baru |
| --- | --- |
| services/llm_service.py | domain/llm policies; infrastructure/llm client_factory, completion gateway, serializers, normalizer; application chat/memory/conversation/diagnostic workflows |
| services/memory_service.py read-path | application/memory/resolve_project_scope dan retrieve_context; domain/memory scope/retrieval/assertion policies |
| services/memory_service.py turn/write | application/conversations begin/complete/persist; application/memory outbox snapshots/leases/process/retry; domain/memory turn/outbox policies |
| Query SQL memory | infrastructure/persistence/memory query adapters + transaction; ports/memory_persistence |
| Summary/title/reindex | application/conversations/process_summary, save_title; application/memory/reindex_vectors |
| main.py loop/schema/logging | workers/*, application/memory/run_maintenance, infrastructure/runtime, persistence/legacy_schema, observability/log_buffer |
| Web planning/URL/ranking | domain/web/intent_policy, url_policy, ranking |
| HTTP search/read | infrastructure/web/searxng_gateway, search_results, search_config, page_reader, workflow_gateway |
| services/ai_usage_service.py | observability/ai_telemetry; observability/operational_events |
| Legacy production bridge | infrastructure/application_wiring; legacy_bridges dihapus |
| Facade settings | Dihapus setelah seluruh consumer memakai settings repository |

Application tidak mengimpor SQLAlchemy/OpenAI/Qdrant/Neo4j/configs/ORM. Response
provider dinormalisasi di gateway; fake gateway/persistence/graph/vector dapat
menggantikan adapter pada unit test. Mixin agregator hanya composition; body
workflow dan policy masing-masing mempunyai satu owner. Tidak ada algoritma kedua
yang dipelihara di facade.

## Metrik struktur

| File/area | Checkpoint tahap 0â€“4 | Sekarang |
| --- | ---: | ---: |
| main.py | 289 baris | 62 baris |
| services/llm_service.py | 1942 baris | 71 baris, forwarding saja |
| services/memory_service.py | 1938 baris | 65 baris, forwarding saja |
| services/web_search_service.py | 357 baris | 26 baris, forwarding saja |
| Modul Python app terbesar | â€” | 293 baris |

Ukuran bukan bukti correctness. Bukti utama tetap contract fixture, failure tests,
source equivalence dan dependency gate.

## Verifikasi

Baseline setelah tahap 0â€“4: **178 tes lulus**.
Tahap 5â€“6: **198 tes lulus**.
Setelah tahap 7: **205 tes lulus**.
Final: **214 tes lulus**, tanpa failure/error/skip.

| Gate | Hasil |
| --- | --- |
| Full offline suite | 214/214 lulus; SQLite/Qdrant sementara; koneksi jaringan ditolak |
| Eval AI/RAG offline | 82/82 lulus; 6 kelompok, fidelity 1.0, accepted=true |
| Architecture | 205 modul, 395 edge, 0 cycle, 0 pelanggaran; production tidak mengimpor services |
| LLM/memory source equivalence | 45 fungsi LLM + 39 memory: 0 selisih setelah normalisasi DI/query/helper extraction |
| Web/telemetry source equivalence | 10 search + 3 reader + 11 telemetry declaration: 0 selisih; metadata logging tambahan dikecualikan secara eksplisit |
| Vector/graph source equivalence | 24 vector algorithms, 17 graph methods, 3 graph write components + query/evidence constants cocok baseline |
| OpenAPI/SSE + prompt digests + graph fixtures | Lulus; fixture tidak diregenerasi |
| Diff/schema/provider/frontend hygiene | Tidak ada perubahan configs/models/schemas/requirements/migrations/frontend; diff whitespace diperiksa terhadap checkpoint |

Test tambahan meliputi fake gateway/neutral response, ambiguity short-circuit,
lease loss, duplicate claim, provider down, partial writes, delete compensation,
summary CAS, title/reindex, interval/failure worker, exceptional shutdown, privacy
allowlist, missing-module import, layer violations dan cycle detection.

Source equivalence bukan bukti formal seluruh wiring; karena itu dijalankan
bersama integration SQLite/Qdrant dan HTTP/SSE fake-provider smoke tests.
Kegagalan sementara saat ekstraksi decorator WebSearchPlan, URL gateway dan sisa
import bridge telah diperbaiki sebelum checkpoint final; tidak ditutupi dengan
perubahan assertion/fixture.

Satu pengulangan suite sempat gagal pada
test_h02_router_and_scope_share_the_total_deadline: wall-clock 187 ms dengan
assertion <180 ms. Pengulangan kelompok 11 tes dan full 214 tes kemudian lulus
tanpa edit kode atau assertion. Tidak diklaim sebagai baseline failure yang
terbukti; margin timing kecil tetap merupakan risiko pada host/CI yang sibuk.

## Eval dan telemetry

Evaluation manifest: evals/manifest.json. Evaluasi membekukan prompt requests,
jawaban/tool-loop fixture, retrieval/scope, graph facts, failure safety dan HTTP/SSE.
**Fidelity fixture bukan nilai kualitas jawaban model live.** Kualitas/factuality
model live dilaporkan not_evaluated, membutuhkan task terpisah dengan dataset
berlabel, provider/cost/privacy approval, dan model/index/prompt version terkunci.

Telemetry baru hanya metadata allowlist: request/session/turn/invocation ID,
provider/model/purpose/prompt version, latency/tokens/cost yang tersedia, source
candidate IDs, tool/count/status, job ID/state. Tidak menambah prompt, isi memory,
query/page body, secret atau lease token ke event baru. Cost/usage yang tidak
tersedia tetap unknown/null. Schema AIInvocation dan accounting tidak diubah.

Autonomous retry tidak bisa memulihkan request ID historis yang sebelumnya tidak
dipersist; session/turn/job menjadi join key durable. Detail ada di
app/observability/README.md.

CI workflow ditambahkan untuk architecture gate, eval dan full tests. Belum
dijalankan di GitHub; hasil di atas adalah eksekusi lokal offline. Pemeriksa source
equivalence membutuhkan tag Git checkpoint lokal, sehingga tidak dipaksakan di CI
yang belum memiliki tag tersebut; CI tetap menjalankan seluruh fixture contract.

## Risiko/debt yang tersisa

1. Facade dan routes compatibility masih dipakai tes legacy/audit lokal.
   Owner maintainer backend; migrasikan import/helper/patch targets per capability,
   pertahankan fixture, lalu hapus setelah nol consumer dan suite hijau.
   Script audit/repair untracked pengguna tidak dibuang atau dijalankan.
2. Legacy schema repair tetap berjalan saat startup production, sesuai baseline.
   Retirement melalui Alembic memerlukan rollout terpisah; rencana di
   Analysis/legacy_schema_retirement_plan.md. Tidak ada schema/data migration di sini.
3. Neo4j/provider/Jina/SearXNG live, kualitas jawaban live, CI host dan load/soak
   produksi tidak diuji. Fixture graph tidak menggantikan integration Neo4j live.
4. Formatter/linter/type checker khusus tidak tersedia di venv saat pekerjaan.
   Syntax/AST, import-boundary/cycle, diff whitespace dan test dilakukan; tidak
   mengklaim mypy/ruff/black telah lulus.
5. Ada call-shape baseline reindex compensation yang mengirim status vector sebagai
   argumen positional, sementara adapter nyata keyword-only. Perilaku lama ini
   dipertahankan, bukan diperbaiki diam-diam; failure-injection fixture melindunginya.
   Perbaikan bug tersebut membutuhkan perubahan perilaku terpisah.
6. Thread yang sudah menjalankan external write tidak bisa dipaksa berhenti oleh
   cancellation coroutine. Lease/idempotency/tombstone/compensation tetap menjadi
   guard; queue/deployment eksternal tidak ditambahkan.
7. Tes deadline wall-clock memiliki margin kecil dan menunjukkan satu kegagalan
   timing intermiten pada pengulangan. Hasil terakhir hijau tidak menghapus risiko
   flakiness tersebut; investigasi/perbaikan test deterministik adalah task terpisah.

## Checkpoint dan rollback

Commit capability, urut:

- 2ef2db5 â€” frozen LLM request contracts.
- 4bf3613 â€” domain LLM policies.
- 63fd54e â€” gateway dan bounded LLM workflows.
- 1f43987 â€” memory read-path (terpisah dari write).
- 42baa6d â€” turn lease dan atomic persistence.
- b68d65c â€” outbox/write lease/retry/cancel/compensation.
- cb45e82 â€” summary/title/reindex + API binding.
- 8a94f20 â€” worker/runtime/bootstrap.
- 4426d83 â€” public memory contracts dan dead-import cleanup.
- ad11e5d â€” owner web/telemetry keluar services.
- a50d42d â€” runtime wiring dan facade settings retirement.
- 81c2277 â€” CI/boundary/eval hardening.
- 643c0e9 â€” whitespace cleanup dengan AST/string bytes tetap identik.

Rollback dilakukan dengan revert capability terbaru ke lama, atau revert seluruh
range setelah refactor-stages-0-4-complete pada worktree yang sudah diamankan.
Jangan menggunakan reset --hard untuk membuang perubahan pengguna.
Tidak membutuhkan rollback schema/data karena refactor ini tidak memigrasikannya.
File settings facade dan bridge lama dapat dipulihkan dari commit Git sebelumnya.

Command lengkap tersedia di backend/TESTING.md. Artefak hasil runtime berada di
.refactor yang di-ignore; tidak masuk commit.
