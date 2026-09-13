# Enterprise Backend Refactor Plan

## 1. Tujuan dan batasan

Dokumen ini adalah rencana refactor backend Claire AI dari struktur `routes/` +
`services/` yang berpusat pada file besar menuju **modular monolith** dengan
batas domain yang tegas. Rencana ini tidak mengubah produk, URL API, payload,
skema database, maupun provider AI pada tahap awal.

Tujuan utama:

- Menurunkan *coupling* dan risiko perubahan pada backend AI/RAG.
- Menjadikan setiap alur bisnis mudah diuji, diamati, dan diubah secara lokal.
- Menghilangkan *god modules*, khususnya `memory_service.py`, `llm_service.py`,
  `neo4j_service.py`, `qdrant_service.py`, dan `chat_routes.py`.
- Menyiapkan batas yang memungkinkan worker, vector retrieval, dan graph
  maintenance diskalakan secara independen bila kelak dibutuhkan.

Non-tujuan:

- Tidak langsung mengubahnya menjadi microservices.
- Tidak mengganti OpenAI, Qdrant, Neo4j, SQLite/SQLAlchemy, atau FastAPI.
- Tidak melakukan perubahan fitur bersamaan dengan refactor struktural.
- Tidak memindahkan seluruh kode dalam satu pull request atau satu commit.

## 2. Kondisi awal yang dipetakan

| Area | Modul saat ini | Tanggung jawab yang bercampur |
| --- | --- | --- |
| HTTP/API | `routes/chat_routes.py` | Chat/SSE, session, project, graph, memory jobs, stats, akses database |
| Orkestrasi memory | `services/memory_service.py` | Scope, retrieval, turn lifecycle, persistence, outbox, summary, reindex |
| Orkestrasi LLM | `services/llm_service.py` | Client/provider, prompt, streaming, tool loop, extraction, routing, title/summary |
| Graph | `services/neo4j_service.py` | Identity, write/query graph, mutation, provenance cleanup, consolidation |
| Vector/RAG | `services/qdrant_service.py` | Client, embedding, chunking, write, search/ranking, maintenance |
| Background process | `main.py` | Startup, migration legacy schema, scheduler loop, worker loop, API bootstrap |

File besar sendiri bukan bug. Masalahnya adalah banyak alasan untuk berubah
berada dalam file yang sama dan layer HTTP, aturan bisnis, serta detail
provider masih berpotongan.

## 3. Prinsip arsitektur target

Arsitektur target menggunakan *ports and adapters* (hexagonal) secara
pragmatis dalam satu deployment modular-monolith.

```text
FastAPI router / SSE
        |
        v
Application use case (satu workflow)
        |
        +--> Domain policies dan entities
        |
        +--> Ports / contracts
                   ^
                   |
     Infrastructure adapters (OpenAI, Qdrant, Neo4j, SQLAlchemy, web)
```

Aturan dependency:

1. Router hanya menangani HTTP, autentikasi/dependency, validasi, dan konversi
   response; router tidak boleh berisi query SQL/Cypher atau logika prompt.
2. Use case mengorkestrasi satu workflow, tetapi tidak mengetahui SDK/provider
   tertentu.
3. Domain policy berisi aturan deterministik dan tidak mengimpor FastAPI,
   SQLAlchemy, OpenAI, Qdrant, maupun Neo4j.
4. Port adalah kontrak yang dipakai application/domain; adapter infrastructure
   mengimplementasikan kontrak tersebut.
5. Tidak ada impor private lintas konteks, misalnya modul memory mengambil
   helper privat dari modul LLM.
6. Kode baru tidak ditambahkan lagi ke `services/` kecuali sebagai compatibility
   facade sementara selama migrasi.

## 4. Struktur target

Struktur ini adalah tujuan akhir, bukan pekerjaan satu kali.

```text
backend/
  app/
    api/
      routers/                 # chat, conversations, projects, memory, graph, system
      dependencies.py
      sse.py
      errors.py
    application/
      chat/                    # start_turn, stream_turn, stop_turn
      conversations/           # history, title, summary
      projects/                # CRUD dan scope
      memory/                  # retrieve, process job, reindex
      graph/                   # read/mutate graph
    domain/
      conversation/            # entities, lifecycle, policies
      memory/                  # retrieval/scope/outbox policies
      llm/                     # prompt/routing/context-budget policies
      graph/                   # identity/fact policies
    ports/
      llm_gateway.py
      vector_store.py
      graph_store.py
      repositories.py
      web_search_gateway.py
    infrastructure/
      llm/
      vector/
      graph/
      persistence/
      web/
    workers/
      memory_outbox_worker.py
      summary_worker.py
      vector_reindex_worker.py
      maintenance_worker.py
    observability/
      tracing.py
      ai_telemetry.py
      diagnostics.py
```

Target ukuran adalah sinyal desain, bukan aturan mekanis:

| Tipe modul | Target umum | Catatan |
| --- | ---: | --- |
| Router/handler | 30–120 baris | Satu resource atau kemampuan API |
| Use case | 80–250 baris | Satu workflow pengguna atau worker |
| Domain policy | 50–250 baris | Aturan bisnis yang mudah dites tanpa I/O |
| Adapter/repository | 150–400 baris | Pecah lagi menurut read/write/admin bila perlu |
| File >400 baris | Harus direview | Boleh hanya bila cohesion masih kuat dan ada alasan eksplisit |

## 5. Guardrail sebelum mulai

Tahap ini wajib selesai sebelum ekstraksi modul pertama.

### 5.1 Version control dan hygiene

- Pastikan backend berada dalam Git repository dan semua perubahan refactor
  berjalan pada branch terpisah.
- Tambahkan ignore policy untuk virtual environment, cache Python, database
  lokal, data Neo4j/Qdrant, log, dan artefak audit yang bersifat runtime.
- Pastikan data produksi/pengembangan tidak ikut tersentuh oleh test atau
  migrasi refactor.

### 5.2 Baseline perilaku

- Jalankan test suite yang sudah ada dan simpan hasil baseline.
- Catat endpoint, method, status code, request/response body, serta event SSE
  yang sudah dipublikasikan.
- Buat *characterization tests* untuk perilaku penting yang belum punya test;
  test ini membekukan perilaku sekarang, bukan mendesain perilaku baru.
- Gunakan fixture/mocking untuk provider eksternal sehingga unit test tidak
  membutuhkan API key atau koneksi internet.

### 5.3 Kontrak kritis yang harus diproteksi

1. Streaming chat: urutan dan bentuk event SSE, handling stop/error.
2. Turn lifecycle: idempotency, `turn_id`, sequence, status response.
3. Memory outbox: lease, retry, cancel, dan kompensasi conversation deletion.
4. Retrieval: project scope, global scope, active/inactive memory, ranking.
5. Knowledge extraction dan graph provenance.
6. Session/project CRUD dan pinning.
7. Pengukuran penggunaan LLM serta diagnostics.

**Definition of done tahap fondasi:** baseline tercatat, test dapat dijalankan
berulang, dan tidak ada perubahan API atau data runtime.

## 6. Roadmap eksekusi aman

Setiap tahap diselesaikan sebagai perubahan kecil, dapat direview, dapat
di-rollback, dan tidak dicampur dengan fitur baru.

### Tahap 0 — Baseline dan observability contract

**Tujuan:** memiliki pagar pengaman sebelum memindahkan kode.

Pekerjaan:

- Menetapkan test command tunggal untuk backend dan dokumentasi cara menjalankannya.
- Menambah contract test HTTP/SSE dan characterization test pada lifecycle
  memory yang paling berisiko.
- Menetapkan correlation identifier: `request_id`, `session_id`, dan `turn_id`
  dalam log/diagnostic yang ada.
- Mencatat dependency graph antarmodul untuk membuktikan cycle import tidak
  bertambah selama refactor.

Keluar bila: test baseline hijau, kontrak streaming terdokumentasi, dan
rollback dapat dilakukan hanya dengan revert commit.

### Tahap 1 — Tipiskan API layer

**Tujuan:** memisahkan transport HTTP dari orkestrasi tanpa mengubah endpoint.

Urutan ekstraksi dari `chat_routes.py`:

1. `api/routers/projects.py`: list/create/update/delete project.
2. `api/routers/conversations.py`: sessions, history, pin, delete.
3. `api/routers/graph.py`: graph read dan graph mutation.
4. `api/routers/memory.py`: job list/retry dan stats terkait memory.
5. `api/routers/chat.py`: synchronous chat dan SSE streaming.
6. `api/sse.py` dan `api/errors.py`: serialisasi SSE dan error mapping bersama.

Setiap router memanggil use case atau facade yang kompatibel. Untuk tahap ini,
isi service lama boleh tetap ada; yang berubah hanya batas transport.

Keluar bila: semua URL/payload sama, router tidak mengakses provider secara
langsung, dan test HTTP/SSE hijau.

### Tahap 2 — Kontrak port dan persistence boundary

**Tujuan:** menghentikan application code bergantung langsung pada provider.

Pekerjaan:

- Definisikan port kecil berbasis kebutuhan use case, bukan interface besar
  `MemoryService`.
- Buat repository untuk conversation, project, message, settings, dan memory
  outbox di atas SQLAlchemy.
- Gunakan dependency injection di API/worker startup untuk menyediakan adapter.
- Pertahankan model SQLAlchemy dan schema yang ada; pemindahan folder model
  bukan prioritas pada tahap ini.

Contoh port inti:

```text
ConversationRepository   # get/create/update/history/turn persistence
MemoryJobRepository      # claim/update/retry/cancel/list
VectorStore              # upsert/search/status/delete
GraphStore               # merge/search/read/mutate/provenance cleanup
LLMGateway               # complete/stream/extract/title/summary
WebSearchGateway         # search/read
```

Keluar bila: use case baru tidak mengimpor SQLAlchemy/Qdrant/Neo4j/OpenAI
langsung dan adapter dapat diganti dengan fake in-memory pada unit test.

### Tahap 3 — Pecah vector retrieval/Qdrant

**Tujuan:** memisahkan pipeline RAG vector tanpa mengubah ranking atau koleksi.

Ekstraksi dari `qdrant_service.py`:

```text
infrastructure/vector/
  qdrant_client_factory.py       # koneksi dan collection lifecycle
  embedding_encoder.py           # model init, embed_text(s), health/warmup
  chunker.py                     # token-aware chunk offsets
  qdrant_vector_store.py         # upsert/reconcile/status/delete
  retrieval_ranker.py            # lexical/recency/hybrid scoring
  vector_maintenance.py          # stats dan reindex support
```

Guardrail khusus:

- Tidak boleh mengubah embedding model, embedding signature, collection name,
  point ID, payload schema, chunking parameter, atau rumus ranking dalam PR
  ekstraksi.
- Gunakan fixture point/payload untuk menguji hasil retrieval sebelum dan
  sesudah pemindahan.

Keluar bila: hasil lookup dan payload write kompatibel, serta `VectorStore`
dipakai application layer alih-alih service Qdrant lama.

### Tahap 4 — Pecah graph/Neo4j

**Tujuan:** menaruh detail Cypher dan lifecycle graph di infrastructure.

Ekstraksi dari `neo4j_service.py`:

```text
domain/graph/
  identity.py                    # canonical identity/entity key rules
  fact_policy.py                 # validasi/mutability policy
infrastructure/graph/
  neo4j_client_factory.py
  neo4j_graph_store.py           # adapter port utama
  graph_writes.py                # merge knowledge/facts
  graph_reads.py                 # search dan graph data
  graph_mutations.py             # node/fact update/delete
  provenance.py                  # conversation cleanup
  consolidation.py               # maintenance/decay
```

Guardrail khusus:

- Snapshot/fixture graph digunakan untuk memastikan entity key, provenance,
  active status, dan mutation semantics tidak berubah.
- Query Cypher tidak tinggal di router atau application use case.

Keluar bila: graph API tetap identik dan semua operasi Neo4j hanya lewat
`GraphStore`.

### Tahap 5 — Pecah LLM pipeline

**Tujuan:** memisahkan model/provider, prompt construction, dan workflow AI.

Ekstraksi dari `llm_service.py`:

```text
domain/llm/
  context_budget.py
  prompt_policy.py
  memory_query_policy.py
  extraction_policy.py
infrastructure/llm/
  client_factory.py
  openai_gateway.py
  response_normalizer.py
application/chat/
  build_chat_context.py
  generate_response.py
  stream_response.py
  execute_web_tool_loop.py
application/memory/
  extract_knowledge.py
  route_memory_query.py
application/conversations/
  generate_title.py
  generate_summary.py
```

Guardrail khusus:

- Prompt content, tool schema, model selection fallback, timeout, streaming
  event sequence, dan token accounting dibekukan oleh test/fixture.
- Prompt diberi version identifier agar perubahan berikutnya dapat dievaluasi.
- LLM gateway menormalkan response provider sebelum dikonsumsi use case.

Keluar bila: application tidak mengenal `AsyncOpenAI`/`OpenAI`, setiap workflow
AI dapat diuji dengan fake gateway, dan tidak ada helper privat lintas modul.

### Tahap 6 — Pecah memory orchestration (tahap paling akhir dan paling sensitif)

**Tujuan:** memecah lifecycle memory tanpa mengorbankan correctness.

Ekstraksi dari `memory_service.py`:

```text
domain/memory/
  scope_policy.py
  retrieval_policy.py
  outbox_policy.py
  turn_policy.py
application/memory/
  resolve_project_scope.py
  retrieve_context.py
  process_outbox_job.py
  retry_due_jobs.py
  reindex_vectors.py
application/conversations/
  begin_turn.py
  complete_turn.py
  persist_interaction.py
  generate_summary.py
  cancel_conversation_jobs.py
```

Urutan wajib di dalam tahap ini:

1. Scope resolution dan retrieval read-path.
2. Turn begin/complete/persistence.
3. Outbox claim/lease/retry/cancel/compensation.
4. Knowledge extraction write-path ke vector dan graph.
5. Summary, title generation, dan reindex/maintenance.

Guardrail khusus:

- Jangan memindahkan read-path dan write-path pada PR yang sama.
- Untuk job/outbox, pertahankan idempotency key, lease token, expiry, dan
  kompensasi delete persis seperti perilaku saat ini.
- Tambahkan test failure injection: provider down, retry duplikat, lease
  expired, conversation terhapus di tengah pekerjaan, dan partial write.

Keluar bila: tidak ada lagi `memory_service.py` sebagai pusat orkestrasi;
semua use case memory memiliki test unit dan integration yang relevan.

### Tahap 7 — Worker runtime dan bootstrap

**Tujuan:** memisahkan lifecycle aplikasi dari pekerjaan background.

Pekerjaan:

- Pindahkan loop outbox retry, summary retry, reindex, dan maintenance dari
  `main.py` ke module `workers/` yang dapat dijalankan/dites sendiri.
- Jadikan `main.py` sebagai composition root: konfigurasi, dependency wiring,
  middleware, router registration, lifecycle start/stop.
- Pisahkan legacy local-schema repair dari API bootstrap dan tetapkan rencana
  penghentian setelah Alembic menjadi satu-satunya jalur migrasi.
- Pertahankan runtime in-process dahulu; evaluasi queue eksternal hanya jika
  observability/throughput membuktikan kebutuhan.

Keluar bila: `main.py` kecil dan hanya merangkai aplikasi, worker bisa diuji
terpisah, serta shutdown membatalkan worker secara aman.

### Tahap 8 — Hardening, evaluasi AI, dan penghapusan compatibility facade

**Tujuan:** menjadikan struktur baru stabil untuk pengembangan jangka panjang.

Pekerjaan:

- Hapus facade/import compatibility dari `services/` setelah semua consumer
  bermigrasi.
- Tambahkan lint import boundary dan cycle detection pada CI.
- Tambahkan test pyramid: unit domain, adapter integration, API contract, dan
  end-to-end smoke test.
- Buat evaluation suite AI/RAG: golden retrieval set, expected graph facts,
  prompt/tool-loop fixtures, dan regresi kualitas jawaban yang terukur.
- Catat telemetry minimum per turn: request/turn ID, provider/model, prompt
  version, latency, token/cost, retrieval candidate IDs, tool usage, job state.

Keluar bila: tidak ada import production ke `services/`, dependency direction
dipatuhi, dan perubahan prompt/retrieval dapat dievaluasi sebelum rilis.

## 7. Strategi kompatibilitas dan rollback

1. **Move, do not rewrite.** PR ekstraksi hanya boleh memindahkan dan
   mengadaptasi dependency; perubahan perilaku adalah PR terpisah.
2. Gunakan compatibility facade sementara, misalnya fungsi lama mendelegasikan
   ke use case/adaptor baru. Facade diberi tanggal penghapusan.
3. Satu bounded context per PR; jangan mencampur perubahan router, database,
   prompt, dan vector ranking dalam satu PR.
4. Jalankan test baseline, test area yang diubah, lalu API/SSE contract test
   sebelum merge.
5. Jika ada regresi, revert PR ekstraksi secara utuh; jangan memperbaiki dengan
   patch ad-hoc di service lama dan baru secara bersamaan.
6. Tidak ada migrasi data pada tahap ekstraksi. Jika suatu saat format data
   perlu berubah, buat rencana migrasi/rollback tersendiri.

## 8. Checklist review untuk setiap PR

- [ ] Hanya satu capability/bounded context yang disentuh.
- [ ] Endpoint, payload, status code, dan event SSE tidak berubah.
- [ ] Tidak ada perubahan schema database, embedding signature, collection,
      Cypher semantics, atau prompt tanpa keputusan eksplisit terpisah.
- [ ] Dependency baru mengikuti arah API → application → domain/ports.
- [ ] Tidak ada import private lintas package atau circular import baru.
- [ ] Unit test dan contract/integration test area terkait lulus.
- [ ] Failure path, cancellation, retry, dan idempotency tetap diuji bila
      workflow memiliki side effect.
- [ ] Log/diagnostic mempertahankan `request_id`, `session_id`, dan `turn_id`.
- [ ] Compatibility facade, bila dibuat, memiliki owner dan kriteria penghapusan.
- [ ] Review diff memisahkan formatting mekanis dari perubahan struktural.

## 9. Urutan prioritas ringkas

```text
0. Baseline test + API/SSE contracts + Git/hygiene
1. Thin routers
2. Ports + SQLAlchemy repositories
3. Qdrant/vector boundary
4. Neo4j/graph boundary
5. LLM pipeline
6. Memory orchestration
7. Worker/bootstrap runtime
8. CI boundary checks + AI evaluation + hapus compatibility layer
```

Urutan ini sengaja menunda `memory_service.py` sampai akhir. Ia merupakan
bagian paling besar sekaligus menyimpan lifecycle write/retry/compensation;
memecahnya sebelum kontrak, port, dan adapter sudah stabil akan memberi risiko
regresi tertinggi.

## 10. Keputusan arsitektur yang perlu dijaga

- Pilih modular monolith sekarang; jangan membuat microservice hanya demi
  pemisahan file.
- Pisahkan deployment/queue hanya bila ada bukti kebutuhan operasional, seperti
  embedding reindex menghambat API, throughput worker tidak cukup, atau domain
  tertentu memerlukan lifecycle dan skalabilitas independen.
- Gunakan nama berdasarkan kemampuan bisnis/workflow (`process_outbox_job`),
  bukan nama generik (`memory_helpers`, `common_service`, `utils`).
- Jadikan evaluasi AI dan observability bagian dari definition of done, bukan
  pekerjaan sesudah refactor selesai.
