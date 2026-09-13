# Rencana eksekusi tahap 5â€“6

Scope: pipeline LLM dan memory orchestration, sesuai roadmap dan aturan wajib.
Baseline checkpoint: tag `refactor-stages-0-4-complete`, commit `33f5356`.
Baseline: 178 test lulus sebelum perubahan. Branch: `refactor/backend-stages-5-6`.

## Urutan capability commit

1. Characterization prompt/request dan dependency baseline, tanpa ekstraksi.
2. Domain LLM prompt/context/reference/extraction policies.
3. Provider client/gateway/response normalization dan workflow chat/tool loop,
   extraction/router/title/summary/diagnosis melalui injected ports.
4. Memory scope resolution dan retrieval read-path; verifikasi dan commit sendiri.
5. Turn begin/complete/persistence dan atomic message/outbox transaction.
6. Outbox claim/lease/retry/cancel/compensation, kemudian extraction write-path.
7. Summary/title/reindex workflows; verifikasi lengkap dan laporan handoff.

Read-path dan write-path tidak digabung dalam commit capability yang sama.
Tidak ada PR eksternal yang dibuat atau digabung dalam task ini.

## Kontrak dan side effect

Prompt bytes, tool schema, model/provider fallback, timeout/retry, token accounting,
HTTP/SSE sequence, begin-turn idempotency/sequence, atomic persistence/outbox,
lease fencing, expiry, duplicate retry, cancellation dan deletion compensation
dibekukan. Schema, ranking, Cypher, embedding/signature dan runtime data tidak
diubah. Tidak ada dependency upgrade atau provider live call.

LLM application memakai completion/web/telemetry ports dan policy deterministik;
SDK response dinormalisasi sebelum mencapai application. Memory application
memakai transaksi/repository ports, vector/graph/LLM ports; SQL tetap di adapter.
Method/module lama hanya forwarding ke single owner, agar consumer dan patch
contract lama bisa dimigrasikan tanpa dua implementasi.

## Verifikasi dan rollback

Jalankan single offline test runner setiap capability, contract HTTP/SSE, prompt
characterization, fake gateway tests, SQLite/outbox failure injection dan vector/
graph fixtures. Jalankan AST extraction equivalence, architecture/cycle gate,
syntax dan diff check sebelum handoff. Test tidak memulai lifespan/worker atau
menyentuh SQLite/Qdrant/Neo4j pengguna.

Rollback: revert commit capability terbaru ke terlama; tanpa reverse migration.
Facade LLM/memory memiliki owner pada application/policy/adapter baru dan hanya
boleh dihapus setelah consumer/patch targets dimigrasikan; target hardening tahap
8. Worker loop/bootstrap tetap pada main sampai tahap 7.
