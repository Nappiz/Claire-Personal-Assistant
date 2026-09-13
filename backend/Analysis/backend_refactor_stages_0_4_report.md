# Laporan refactor backend tahap 0â€“4

Tanggal: 13 September 2026. Scope mengikuti `enterprise_backend_refactor_plan.md`
dan `REFACTORING_RULES.md`. Frontend dan tahap 5â€“8 tidak dikerjakan.

## 1. Hasil dan batas perubahan

Tahap 0â€“4 telah diimplementasikan sebagai ekstraksi bertahap, bukan rewrite.
Transport HTTP, application orchestration, repository, vector adapter, dan graph
adapter sekarang mempunyai batas modul yang terpisah. Semua 78 modul Python di
`backend/app` dapat diparse; modul terbesar 293 baris. Ukuran bukan satu-satunya
quality gate: pemisahan dilakukan menurut tanggung jawab dan arah dependency.

`memory_service.py` dan `llm_service.py` belum dipecah menjadi pipeline baru.
Memory hanya diarahkan ke adapter storage baru; lifecycle, lease, retry,
compensation, reindex, dan algoritma AI tetap pada owner lama sampai tahap 5â€“6.

Repository awal belum mempunyai Git. Baseline lokal dibuat pada branch
`refactor/backend-stages-0-4`, commit `9b7908a`, tag
`refactor-backend-baseline`. Commit berikutnya dipisahkan menurut capability.
Tidak ada push atau remote baru. File lama yang tidak terkait tetap dipertahankan
dan tidak dimasukkan secara massal ke commit.

## 2. Implementasi per tahap

| Tahap | Implementasi | Bukti keluar |
| --- | --- | --- |
| 0 | Runner offline dengan SQLite/Qdrant sementara; fixture OpenAPI/SSE; correlation request/session/turn ID; snapshot dependency graph; baseline Git | Baseline 163 test hijau sebelum ekstraksi; tidak memakai data lokal |
| 1 | Router projects, conversations, graph, memory, chat, system, settings; HTTP error mapping dan SSE serializer terpisah; use case application | Kontrak OpenAPI tetap sama; test HTTP/SSE hijau; router tidak mengakses SDK/provider langsung |
| 2 | Protocol ports, dependency composition, SQLAlchemy repositories dan unit of work | Application tidak mengimpor ORM/provider/transport; fake UOW dan repository SQLite teruji |
| 3 | Client lifecycle, encoder, chunker, vector writes, retrieval ranker, maintenance, serta adapter `VectorStore` | Fixture Qdrant in-memory dan 24 algoritma baseline setara; application memakai port |
| 4 | Domain identity/fact policy; Neo4j connection, reads, writes, mutations, provenance, consolidation, adapter `GraphStore` | 11 skenario graph golden sesuai baseline; Cypher hanya di infrastructure graph; transaksi write tetap satu |

## 3. Modul utama dan owner

- `app/api/routers/*`, `app/api/sse.py`, `app/api/errors.py`: HTTP, validation,
  serialization, dan pemetaan kegagalan provider pada batas transport.
- `app/application/*`: use case chat, projects, conversations, graph, memory job,
  system stats, dan settings. Dependency diberikan melalui port/UOW.
- `app/ports/*`: kontrak repository, vector, graph, LLM, memory workflow, dan
  web search. Port web search disiapkan untuk tahap selanjutnya, bukan pipeline
  web baru yang telah diimplementasikan.
- `app/infrastructure/persistence/*`: query ORM dan transaksi SQLAlchemy.
  Primitive memory outbox tersedia di repository; claim/lease/retry orchestration
  tetap pada legacy memory workflow sesuai scope tahap 6.
- `app/infrastructure/vector/*`: satu owner state client/encoder; lifecycle,
  embedding, chunking, writes, ranking, dan maintenance terpisah.
- `app/domain/graph/*`: identity dan evidence/fact policy murni.
- `app/infrastructure/graph/*`: koneksi, Cypher, reads/mutations/provenance,
  consolidation dan write components. Entity write, fact write, dan retraction
  tetap dieksekusi dalam callback transaksi yang sama.
- `app/observability/correlation.py`: ContextVar dan filter correlation log;
  tidak menambah field response atau mencatat prompt/memory/secret.

## 4. Kontrak yang dipertahankan

- HTTP method, URL, parameter, status, response schema dan OpenAPI paths/components.
- Framing Unicode SSE, headers, urutan event, partial delta dan error handling.
- Project scope, conversation/history/pin semantics, delete tombstone,
  provenance cleanup dan retry setelah storage failure.
- Model ORM, Pydantic schema, konfigurasi, migration, dan sumber LLM/provider.
- Embedding model/signature, nama collection, point ID, payload, chunk offsets,
  lexical/recency scoring dan retrieval ranking.
- Canonical entity key, fact evidence policy, active status, provenance,
  query parameters, mutation semantics dan batas transaksi Neo4j.
- Memory idempotency, lease/retry/cancel/compensation dan token accounting tetap
  mengikuti implementasi lama; tidak dilakukan bugfix fitur terselubung.

Tidak ada migration, reindex runtime, reset graph/vector, startup worker live,
perubahan dependency, atau panggilan provider eksternal selama verifikasi.
Diff model/schema/config/migration/LLM/web-search/frontend terhadap baseline kosong.

## 5. Verifikasi akhir

Jalankan dari root repository:

```powershell
.\backend\venv\Scripts\python.exe backend\scripts\run_tests.py
.\backend\venv\Scripts\python.exe backend\scripts\check_architecture.py --baseline-ref refactor-backend-baseline
.\backend\venv\Scripts\python.exe backend\scripts\verify_extraction.py
git diff --check
```

Hasil akhir:

- **178 test lulus, 0 failure, 0 error**. Baseline 163 terdiri dari 161 test lama
  dan 2 contract test tahap 0; tambahan 15 test memproteksi HTTP, repository,
  vector, graph, dan correlation.
- Dependency graph: **111 modul, 219 edge, 0 circular import, 0 pelanggaran
  dependency direction**. Baseline juga 0 cycle.
- Extraction verifier: **24 algoritma vector, 17 metode graph, dan 3 write
  component** setara AST baseline; konstanta query dan keseluruhan evidence
  policy juga sesuai. Untuk query yang dipindah dari nested callback, hanya
  whitespace indentasi dinormalisasi dalam pembandingan.
- Qdrant benar-benar dijalankan in-memory dengan encoder fixture, termasuk
  stable point ID, signature/scope payload, reconciliation, retrieval,
  inactive status, dan session deletion.
- Neo4j memakai recording driver deterministik dan golden fixture dari kode
  baseline: merge, retraction, ambiguous identity, graph read/search, update
  node/fact, delete node/fact, provenance cleanup, dan consolidation. Query,
  parameter, hasil dan jumlah transaksi dibandingkan; write failure teruji.
- Syntax AST seluruh modul baru valid; `git diff --check` lulus.

Temuan selama implementasi tidak disembunyikan: masalah runner Windows/logging
diselesaikan sebelum baseline ekstraksi. Pemeriksaan akhir juga menemukan
regresi bentuk argumen pada callback compensation vector; forwarding diperbaiki
dan targeted 22 test serta seluruh 178 test kemudian dijalankan ulang dan lulus.

## 6. Compatibility debt dan kriteria penghapusan

| Facade/bridge sementara | Single implementation owner | Kapan boleh dihapus |
| --- | --- | --- |
| `routes/chat_routes.py` | Router/use case/SSE/errors baru; explicit forwarding globals | Setelah semua importer dan patch target lama dimigrasikan; paling lambat hardening tahap 8 |
| `routes/settings_routes.py`, `services/settings_service.py` | API settings dan settings repository | Setelah consumer lama memakai API/repository baru dan contract test tetap hijau |
| `services/diagnostic_service.py` | `app/domain/diagnostics.py` | Setelah import legacy seluruhnya dimigrasikan |
| `services/qdrant_service.py` | `app/infrastructure/vector/*` | Setelah memory workflow tahap 6 dan test patch memakai adapter baru; validasi tahap 8 |
| `services/neo4j_service.py` | `app/infrastructure/graph/*` | Setelah seluruh legacy class/singleton importer dan patch target dimigrasikan |
| `services/memory_policy.py` | `app/domain/graph/fact_policy.py` | Setelah seluruh policy importer dimigrasikan |
| `LegacyLLMGateway` | `services/llm_service.py` | Diganti gateway/pipeline nyata pada tahap 5 |
| `LegacyMemoryWorkflow` | `services/memory_service.py` | Diganti use case/outbox workflow pada tahap 6; bootstrap worker pada tahap 7 |
| `app/compatibility.py` | Mekanisme forwarding saja, tanpa business logic | Setelah facade di atas tidak lagi memiliki consumer; tahap 8 |

Legacy facade meneruskan pembacaan dan patch/write attribute ke owner tunggal,
bukan mempertahankan dua implementasi. Modul baru tidak boleh menambah pemakaian
facade lama. Adapter vector mempertahankan forwarding bentuk argumen callback
status lama; pemanggil positional pada compensation reindex yang sudah ada tidak
dibetulkan diam-diam. Evaluasi bug tersebut secara terpisah pada tahap 6.

## 7. Risiko tersisa dan rollback

Verifikasi Neo4j bukan integrasi server live; encoder fixture bukan evaluasi
kualitas semantic embedding, dan tidak ada panggilan LLM/web provider live.
Sebelum rollout production, jalankan smoke/integration test di staging terisolasi
dengan fixture yang sama dan kredensial staging. Black/Ruff/mypy belum tersedia
atau dikonfigurasi pada environment ini; tidak diinstal sebagai scope tambahan.
AST boundary gate tidak menggantikan type checking penuh.

Modul LLM/memory lama masih besar dengan sengaja. Jangan menganggap tahap 5â€“8
sudah selesai atau menghapus bridge sebelum migrasi consumer dan quality gate.
Unused config/helper legacy di luar jalur runtime belum dibersihkan massal.

Rollback memakai revert commit capability di branch ini, urutan terbaru ke
terlama. Untuk rollback seluruh pekerjaan, review daftar
`git log --oneline refactor-backend-baseline..HEAD`, lalu revert commit refactor
yang disetujui; jangan memakai reset hard atau menimpa perubahan pengguna.
Karena schema/payload/data tidak dimigrasikan, rollback tidak memerlukan reverse
migration atau restore collection. Jalankan kembali suite setelah rollback.
