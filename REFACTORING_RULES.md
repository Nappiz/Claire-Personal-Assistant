# Aturan Wajib Refactor

> **Status: wajib.** Dokumen ini mengikat semua developer dan AI agent yang
> melakukan refactor di repository ini. Pelanggaran hanya boleh dilakukan
> melalui pengecualian tertulis yang disetujui pemilik sistem.

## 1. Tujuan

Refactor adalah perubahan struktur internal yang **mempertahankan perilaku
eksternal**. Tujuannya adalah meningkatkan cohesion, menurunkan coupling,
memperjelas ownership, dan memperkuat kemampuan testing/observability.

Refactor bukan alasan untuk sekaligus:

- mengubah fitur atau product requirement;
- mengubah API, payload, event SSE, schema database, atau data production;
- mengganti provider/model AI, embedding model, prompt, ranking, atau timeout;
- melakukan migrasi dependency besar;
- melakukan formatting massal yang mengaburkan diff.

Jika salah satu perubahan di atas memang dibutuhkan, perubahan tersebut harus
menjadi pekerjaan/PR terpisah dengan rencana, acceptance criteria, dan rollback
plan sendiri.

## 2. Cakupan dan otorisasi

Sebelum mengubah kode, pelaksana wajib:

1. Membaca dokumen ini dan instruksi `AGENTS.md` yang berlaku.
2. Mengidentifikasi apakah pekerjaan benar-benar refactor atau perubahan
   perilaku yang menyamar sebagai refactor.
3. Mendefinisikan scope modul, kontrak yang harus dipertahankan, risiko, dan
   test yang akan dijalankan.
4. Memastikan tugas atau persetujuan pemilik sistem memang mengizinkan scope
   refactor tersebut.

Untuk tugas yang hanya meminta analisis/perencanaan, **dilarang mengubah kode,
konfigurasi, data, migration, dependency, atau test baseline**.

## 3. Prinsip tidak dapat dinegosiasikan

### 3.1 Preserve behavior

- Endpoint, HTTP method, status code, request/response body, dan event SSE
  harus identik kecuali ada persetujuan eksplisit untuk perubahan kontrak.
- Urutan lifecycle chat/memory tidak boleh berubah: begin turn, stream/complete,
  persistence, outbox, retry, cancel, dan compensation.
- Refactor tidak boleh mengubah prompt, tool schema, provider fallback, model
  selection, embedding signature, collection name, point ID, chunking parameter,
  retrieval ranking, atau query semantics secara diam-diam.
- Schema dan data database tidak boleh diubah dalam PR refactor struktural.

### 3.2 Scope kecil dan dapat direview

- Satu PR/commit fokus pada satu bounded context atau satu capability.
- Jangan mencampur refactor dengan feature, bug fix perilaku, dependency update,
  migration data, atau mass formatting.
- Bila sebuah diff sulit dijelaskan dalam satu kalimat, pecah menjadi tahap yang
  lebih kecil.
- Jangan melakukan big-bang rewrite atau memindahkan seluruh backend sekaligus.

### 3.3 Move, do not rewrite

- Ekstrak kode dengan perubahan semantik seminimal mungkin.
- Pindahkan fungsi beserta test yang melindunginya sebelum memperbaiki desain
  internalnya lebih jauh.
- Perubahan logika setelah ekstraksi stabil dilakukan dalam PR terpisah.
- Jangan menduplikasi sumber kebenaran. Compatibility facade sementara wajib
  mendelegasikan ke implementasi baru, bukan memelihara dua implementasi aktif.

### 3.4 Dependency direction

Arsitektur yang wajib dijaga:

```text
API / router  ->  application use case  ->  domain + ports
                                             ^
                                             |
                                    infrastructure adapters
```

- Router hanya menangani HTTP/SSE, validasi, dependency injection, dan mapping
  response/error.
- Use case mengorkestrasi satu workflow; tidak mengandung SQL, Cypher, atau SDK
  OpenAI/Qdrant/Neo4j secara langsung.
- Domain policy tidak mengimpor FastAPI, SQLAlchemy, SDK provider, atau kode
  transport.
- Infrastructure mengimplementasikan port; ia tidak menentukan business flow.
- Dilarang membuat circular import atau mengimpor helper privat lintas package.
- Dilarang menambah kode baru ke `services/` sebagai lokasi permanen. Folder itu
  hanya boleh menjadi compatibility facade selama migrasi dan harus memiliki
  rencana penghapusan.

## 4. Prosedur wajib setiap refactor

### Langkah 1 — Discovery dan baseline

Sebelum edit:

- Baca file yang akan diubah, direct caller/callee, schema terkait, serta test
  yang sudah ada.
- Petakan public contract dan side effect: HTTP/SSE, database, vector store,
  graph store, LLM, web tool, background job, atau filesystem.
- Jalankan test baseline yang relevan. Bila baseline sudah gagal, jangan klaim
  kegagalan tersebut disebabkan refactor; laporkan kondisi awalnya.
- Jika behavior belum tertutup test, tambahkan characterization/contract test
  terlebih dahulu atau dapatkan persetujuan eksplisit atas risikonya.

### Langkah 2 — Rencana perubahan

Setiap PR/task refactor harus mempunyai ringkasan singkat:

```text
Capability/bounded context:
Kontrak yang dipertahankan:
Modul asal -> modul tujuan:
Side effect yang terdampak:
Test baseline dan test sesudah perubahan:
Risiko serta rollback:
Compatibility facade dan tanggal/kriteria penghapusannya (jika ada):
```

Untuk pekerjaan sedang/besar, rencana harus merujuk ke
`backend/Analysis/enterprise_backend_refactor_plan.md` dan menyebut tahap
roadmap yang sedang dikerjakan.

### Langkah 3 — Implementasi

- Gunakan pemindahan bertahap: buat module tujuan, pindahkan satu cohesive unit,
  ubah consumer, jalankan test, lalu lanjutkan unit berikutnya.
- Pertahankan nama dan signature internal terlebih dahulu bila itu mengurangi
  risiko. Penyederhanaan API internal dilakukan setelah boundary stabil.
- Pastikan hanya ada satu owner setiap aturan bisnis dan setiap write side
  effect.
- Bersihkan import, dead code, dan compatibility facade hanya setelah seluruh
  consumer sudah bermigrasi dan test hijau.

### Langkah 4 — Verifikasi dan review

Sebelum menyatakan selesai:

- Jalankan formatter/linter/type check yang tersedia untuk area terkait.
- Jalankan unit test area yang diubah, lalu integration/API contract test yang
  mencakup side effect-nya.
- Untuk alur chat, jalankan test SSE/streaming; untuk memory, uji retry,
  cancellation, dan idempotency; untuk graph/vector, uji fixture hasil read dan
  write.
- Periksa dependency baru untuk circular import dan pelanggaran arah layer.
- Review diff untuk memastikan tidak ada perubahan kontrak/perilaku terselubung.

## 5. Aturan khusus backend AI/RAG

### 5.1 LLM dan streaming

- Prompt, system instruction, tool definition, model/provider routing, timeout,
  retry, dan token accounting dianggap kontrak perilaku.
- Streaming harus mempertahankan event type, ordering, termination semantics,
  penanganan abort, dan payload error.
- Response provider harus dinormalisasi pada gateway/adapter; application code
  tidak boleh bergantung pada bentuk mentah SDK provider.
- Setiap perubahan prompt atau model harus memiliki versi, evaluation evidence,
  dan PR terpisah dari refactor struktur.

### 5.2 Memory, outbox, dan background job

- Job harus mempertahankan idempotency key, lease token, expiry, retry policy,
  cancellation, dan kompensasi saat conversation terhapus.
- Read-path dan write-path memory tidak boleh direfactor dalam PR yang sama.
- Side effect ke database, vector, dan graph harus dapat ditelusuri dengan
  `request_id`, `session_id`, dan `turn_id`.
- Jangan mengubah urutan persistence/outbox/extraction tanpa rencana perubahan
  data dan failure-injection test.

### 5.3 Retrieval dan vector store

- Embedding model/signature, collection, payload schema, point ID, chunking,
  filter scope, dan rumus ranking adalah contract data/retrieval.
- Refactor adapter Qdrant wajib menggunakan fixture yang memverifikasi payload
  write dan urutan/isi kandidat retrieval.
- Reindex atau migrasi vector tidak boleh dijalankan sebagai efek samping PR
  refactor.

### 5.4 Knowledge graph

- Canonical identity/entity key, provenance, active/inactive status, dan fact
  mutation semantics dianggap kontrak.
- Detail Cypher hanya boleh berada di adapter infrastructure graph.
- Refactor graph wajib menguji read, merge, update/delete, dan cleanup
  provenance dengan fixture graph yang stabil.

## 6. Data, security, dan operasi

- Dilarang menjalankan perintah destruktif, reset data, wipe collection, atau
  migration database tanpa otorisasi eksplisit dan target yang sudah diverifikasi.
- Test tidak boleh memakai atau merusak database/data lokal pengguna; gunakan
  fixture, temporary database, atau environment terisolasi.
- Secret, API key, database lokal, virtual environment, cache, log, dan runtime
  data tidak boleh masuk ke commit.
- Jangan menambahkan logging yang merekam prompt sensitif, API key, isi memory
  pribadi, atau data pengguna tanpa kebijakan redaction yang disetujui.
- Perubahan scheduler/worker harus mempertahankan startup, shutdown, cancellation,
  dan retry safety.

## 7. Quality gate minimum

Refactor tidak boleh ditandai selesai jika salah satu kondisi berikut belum
dipenuhi:

- [ ] Scope dan kontrak yang dipertahankan terdokumentasi.
- [ ] Test baseline relevan diketahui hasilnya.
- [ ] Test area yang diubah lulus.
- [ ] Contract test HTTP/SSE lulus bila API chat terdampak.
- [ ] Test idempotency/retry/cancel lulus bila memory/job terdampak.
- [ ] Test fixture vector/graph lulus bila adapter terkait terdampak.
- [ ] Tidak ada perubahan schema/data/provider/prompt tersembunyi.
- [ ] Tidak ada circular import atau pelanggaran dependency direction baru.
- [ ] Diff bebas dari file runtime, secret, dan perubahan tak terkait.
- [ ] Rollback path jelas: revert commit/PR tidak meninggalkan data setengah jadi.
- [ ] Compatibility facade, jika ada, memiliki owner serta kriteria penghapusan.

## 8. Kriteria selesai untuk AI agent

Pada laporan akhir refactor, AI agent wajib menyampaikan:

1. Capability dan batas scope yang direfactor.
2. Kontrak yang dipertahankan.
3. File/module yang dipindah atau dibuat.
4. Test/verification yang dijalankan beserta hasilnya.
5. Risiko tersisa, baseline failure, atau test yang belum dapat dijalankan.
6. Compatibility facade/debt yang masih ada dan langkah penghapusannya.

AI agent dilarang mengklaim refactor aman tanpa menjalankan verifikasi yang
proporsional atau dengan menyembunyikan kegagalan baseline/test.

## 9. Pengecualian

Pengecualian terhadap aturan ini harus tertulis dalam task/PR dan menyebutkan:

- aturan yang dikecualikan;
- alasan bisnis/teknis;
- risiko yang diterima;
- mitigasi serta rollback;
- persetujuan pemilik sistem.

"Lebih cepat" atau "sekalian dirapikan" bukan alasan yang cukup untuk
mengecualikan aturan kontrak, data safety, atau testing.

## 10. Penegakan

- Reviewer wajib meminta perbaikan atau menolak PR yang tidak memenuhi quality
  gate ini.
- AI agent wajib berhenti dan meminta arahan bila scope berubah menjadi feature,
  perubahan contract, migration data, atau tindakan destruktif yang belum
  diotorisasi.
- Untuk roadmap backend saat ini, gunakan
  `backend/Analysis/enterprise_backend_refactor_plan.md` sebagai urutan kerja
  dan dokumen ini sebagai aturan pelaksanaannya.
