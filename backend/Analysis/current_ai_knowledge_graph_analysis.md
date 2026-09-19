# Analisis Terkini — AI & Knowledge Graph Claire

> **Tanggal audit:** 9 September 2026  
> **Metode:** static code review terhadap jalur chat, retrieval, extraction, Qdrant, Neo4j, lifecycle memory, dan endpoint koreksi yang ada saat ini. Dokumen ini menilai kode *saat ini*, termasuk perbaikan Critical/High/Medium sebelumnya.  
> **Batasan:** tidak ada pengujian terhadap data produksi maupun load/concurrency test. Temuan yang menyebut deployment/network diberi kondisi eksplisit.

## Verdict

Tidak ada temuan yang diklasifikasikan **Critical** dari kode yang diperiksa. Perbaikan sebelumnya sudah menutup beberapa risiko paling besar: collision nama tidak lagi memakai unique-name global, Qdrant memakai ID event acak, extraction menerima konteks ringkas, fact memiliki status temporal, dan graph mempunyai endpoint koreksi granular.

Masih ada risiko **High**, terutama pada durability dan lifecycle memori. Ringkasannya:

| Severity | Jumlah | Ringkasan |
|---|---:|---|
| Critical | 0 | Tidak ada yang terbukti dari static review. |
| High | 4 | Current fact dapat dipruning otomatis; write pipeline parsial; penghapusan session meninggalkan graph; control plane tanpa autentikasi bila backend terekspos. |
| Medium | 5 | Qdrant selalu memberi top-k tanpa ambang relevansi; person bisa terfragmentasi; extraction LLM belum tervalidasi ketat; temporal replacement terlalu lebar; konteks extractor pendek. |
| Low | 3 | Recall singkatan pendek berkurang; provenance historis kosong; payload provenance dapat terus membesar. |

---

## High

### H1. Current fact dapat terhapus otomatis hanya karena lama tidak disebut

**Bukti kode:** `services/neo4j_service.py`, `consolidate_memory()`.

Maintenance menurunkan `importance` **seluruh node** setiap hari dengan faktor `0.9 ** days_passed`, lalu melakukan `DETACH DELETE` bila `importance < 0.2` dan `updated_at` lebih dari 30 hari. Query forget tersebut tidak memeriksa apakah node masih memiliki relationship `is_current = true`, tidak melihat `last_confirmed_at` edge, dan tidak membedakan fakta mutable dari fakta penting yang stabil.

Secara matematis, node dengan importance awal sekitar `1.0` menjadi sekitar `0.042` setelah 30 hari decay harian (`0.9^30`). Artinya fakta yang benar tetapi tidak dibahas ulang—misalnya keluarga, pendidikan, atau pekerjaan yang masih aktif—dapat dihapus beserta seluruh edge-nya setelah melewati syarat umur. Status temporal yang sudah ditambahkan tidak melindungi fact dari pruning node ini.

**Dampak:** Claire dapat kehilangan ingatan jangka panjang yang masih valid tanpa tindakan user.

**Rekomendasi:** jangan delete node yang masih terhubung ke fact aktif. Jadikan `last_confirmed_at` edge sebagai dasar expiry untuk fakta mutable saja; fakta immutable atau fact `is_current=true` sebaiknya hanya di-decay/ranking, bukan dihapus otomatis.

---

### H2. Pipeline penyimpanan memory tidak atomik dan tidak mempunyai retry/outbox

**Bukti kode:** `services/memory_service.py`, `save_interaction()`; `services/qdrant_service.py`, `save_memory()`.

`save_interaction()` melakukan urutan berikut:

1. Commit user message dan assistant response ke SQLite.
2. Menulis full interaction ke Qdrant.
3. Menjalankan LLM extraction.
4. Menulis hasilnya ke Neo4j.

Setelah SQLite commit, `save_memory()` memanggil `client.upsert()` tanpa penanganan kegagalan di caller. Bila Qdrant/upsert/embedding gagal, exception menghentikan background task sebelum extraction dan Neo4j merge dijalankan. Bila extraction gagal, fungsi mengembalikan node/edge kosong dan tidak ada retry atau status pekerjaan yang dapat diproses ulang.

Karena task dieksekusi setelah respons chat dikirim, user menerima kesan percakapan sudah tersimpan padahal state dapat menjadi parsial: SQLite ada, Qdrant/graph tidak ada; atau Qdrant ada tetapi graph tidak ada.

**Dampak:** fakta dapat hilang permanen dari long-term memory, dan provenance SQLite saja tidak menyediakan mekanisme replay otomatis.

**Rekomendasi:** buat durable outbox/job record di SQLite dengan status per tahap (`pending`, `vector_saved`, `extracted`, `graph_saved`, `failed`), retry dengan backoff, dan endpoint/admin job untuk replay dari message source. Qdrant failure juga tidak boleh menghalangi extraction graph.

---

### H3. Menghapus session tidak menghapus/menandai knowledge graph dan memutus provenance

**Bukti kode:** `routes/chat_routes.py`, `DELETE /sessions/{session_id}`; `services/neo4j_service.py`, provenance edge/node.

Endpoint session delete menghapus `Message` dan `Conversation` dari SQLite lalu menghapus vector Qdrant berdasarkan `session_id`. Tidak ada operasi Neo4j. Fact dan node hasil extraction tetap hidup, termasuk fact yang berstatus `is_current=true`.

Kini graph menyimpan `source_conversation_id` dan `source_message_id`. Setelah session dihapus, ID provenance tersebut menjadi dangling: Claire masih dapat menggunakan fakta itu, tetapi UI tidak dapat membuka percakapan/pesan yang menjadi bukti asalnya.

**Dampak:** user yang menghapus percakapan dapat tetap "diingat" oleh graph; audit source juga menjadi tidak dapat diverifikasi.

**Rekomendasi:** tentukan policy eksplisit saat delete session. Pilihan aman: tandai source sebagai `source_deleted=true`, hilangkan session/message ID dari daftar provenance, lalu nonaktifkan atau hapus fact hanya bila session itu adalah satu-satunya source. Bila retention graph memang disengaja, API harus menjelaskan bahwa delete session tidak berarti delete knowledge.

---

### H4. Endpoint control plane dan memory correction tidak memiliki autentikasi/otorisasi

**Kondisi:** menjadi High bila backend dapat diakses oleh proses/device lain; tidak dapat dipastikan dari repository apakah deployment dibatasi ke localhost.

**Bukti kode:** tidak ada dependency autentikasi pada `routes/chat_routes.py` maupun `routes/settings_routes.py`.

Endpoint berikut menerima request tanpa identitas user/role:

- `GET`/`POST /api/v1/settings` — termasuk nilai `api_keys` yang dipakai `get_llm_client()`.
- `POST /api/v1/settings/memory/consolidate` — menerima `days_passed` tanpa range guard; nilai besar dapat mempercepat decay/pruning graph.
- `PATCH`/`DELETE /api/v1/memory/graph/node/...` dan `/fact/...` — dapat mengubah atau menghapus memory granular.
- `GET /api/v1/logs` — dapat menampilkan log yang berisi potongan pesan user.

CORS localhost bukan autentikasi dan tidak membatasi client non-browser.

**Dampak:** pihak yang mencapai backend dapat membaca/mengubah konfigurasi serta menghapus atau merusak memory.

**Rekomendasi:** sebelum backend dipublikasikan, tambahkan auth wajib, authorization khusus untuk destructive/admin routes, validasi `days_passed` (misalnya `0 < x <= 30`), dan jangan pernah mengembalikan secret melalui settings/log endpoint.

---

## Medium

### M1. Qdrant selalu menginjeksi top-k tanpa score threshold atau reranking

**Bukti kode:** `services/qdrant_service.py`, `search_memory()`; `services/memory_service.py`, `retrieve_context()`.

Saat router menghasilkan keyword, `search_memory()` selalu mengembalikan tiga nearest-neighbor dari seluruh collection. Tidak ada `score_threshold`, filter metadata/topik, atau reranking. Hasil tersebut disisipkan ke `<past_conversations>` walaupun similarity sebenarnya rendah.

Instruksi prompt dan focus boundary memang mengurangi risiko Claire membahas ulang topik yang salah, tetapi mereka bukan filter deterministik. Memori yang tidak relevan masih menambah token, bisa menggeser perhatian model, dan berpotensi memunculkan detail lama secara tidak tepat.

**Rekomendasi:** simpan dan evaluasi similarity score, gunakan ambang minimum yang dievaluasi melalui data nyata, dan/atau rerank menggunakan keyword/entity overlap. Pertimbangkan filter per `session_id` ketika konteks yang diminta jelas bersifat session-local.

---

### M2. Person tanpa `identity_context` selalu menjadi identitas baru

**Bukti kode:** `services/neo4j_service.py`, `_entity_key()`.

Untuk `Person` selain `nafiz` dan `claire`, bila `identity_context` kosong, code membuat key `person:unresolved:<uuid4>`. Ini aman terhadap homonym collapse, tetapi tidak ada mekanisme untuk menyatukan mention orang yang sama pada pesan berikutnya ketika user belum memberikan pembeda eksplisit.

Contoh: dua pesan terpisah yang masing-masing hanya menyebut "Cia" dapat membuat dua node berbeda. Fakta tentang satu orang kemudian tersebar, menurunkan recall dan membuat graph tetap hairball walaupun tidak lagi salah merge.

**Rekomendasi:** tambahkan state entity-resolution per session/conversation dan kandidat entity yang harus dikonfirmasi. Merge hanya jika ada bukti eksplisit (alias, identity context sama, atau konfirmasi user), tetapi gunakan reference session agar mention berikutnya tidak selalu membuat UUID baru.

---

### M3. Hasil extraction LLM langsung menjadi fact tanpa validasi semantik atau confidence

**Bukti kode:** `services/llm_service.py`, `extract_knowledge()` dan `_sanitize_extracted_knowledge()`; `services/memory_service.py`, `save_interaction()`.

Sanitasi output saat ini hanya menolak node/koneksi kata ganti generik dan item non-dict. Tidak ada validasi bahwa semua edge memakai node ID yang valid sebelum merge (backend hanya skip), tidak ada schema model yang ketat untuk label/relation/`supersedes`, tidak ada confidence score, dan tidak ada jalur "pending confirmation" untuk fakta berisiko.

Prompt extraction memang melarang asumsi, tetapi model tetap satu-satunya penentu apakah suatu teks adalah fakta. Halusinasi atau salah interpretasi yang lolos prompt langsung ditulis sebagai fact aktif dan masuk retrieval sampai user menemukan lalu memperbaikinya.

**Rekomendasi:** tambahkan Pydantic schema strict untuk output extractor, relation allowlist/normalisasi, confidence, dan status `pending_review` untuk fact dengan confidence rendah atau klaim mutable/sensitif. Hanya `current` fact tervalidasi yang boleh masuk retrieval default.

---

### M4. `replaces_current_relation` dapat menonaktifkan seluruh fact aktif dengan tipe relation yang sama

**Bukti kode:** `services/neo4j_service.py`, `merge_knowledge()`.

Bila extractor mengeluarkan `replaces_current_relation: true`, code menjalankan `MATCH (source)-[old:RELATION]->()` lalu menonaktifkan semua fact aktif lain dari source dengan relation tersebut. Tidak ada cardinality policy per relation atau verifikasi bahwa relasi memang mutually exclusive.

Walaupun prompt memberi instruksi agar flag dipakai hanya untuk penggantian eksplisit, model dapat salah menganggap perubahan pekerjaan sebagai penggantian total, padahal user mungkin memiliki dua pekerjaan, dua lokasi, atau beberapa status yang tetap valid.

Fact lama tidak hilang secara fisik dan dapat diaktifkan ulang lewat API, sehingga risikonya tidak setingkat data loss permanen, tetapi Claire akan berhenti melihat fact yang sebenarnya masih benar.

**Rekomendasi:** gunakan allowlist relation yang benar-benar single-valued (`LIVES_IN` misalnya), atau wajibkan `supersedes` dengan `fact_id` untuk relation multi-valued. Untuk `WORKS_AT`/`WORKS_AS`, pertimbangkan hubungan berperiode (`valid_from`, `valid_to`) daripada penggantian global.

---

### M5. Konteks extractor dibatasi empat message sebelumnya

**Bukti kode:** `routes/chat_routes.py` mengirim `session_history[-4:]`; `services/memory_service.py` kembali membatasi `[-4:]`; `services/llm_service.py`, `_format_extraction_history(limit=4)`.

Ada tiga lapis pembatas yang efektif membuat extractor hanya melihat empat message sebelumnya. Bila subject disebut lebih awal dari window tersebut dan user kemudian memberi jawaban eliptis/pronominal, extractor tidak dapat meresolve referensi. Guard kata ganti mencegah node sampah, tetapi konsekuensinya adalah fakta baru diam-diam tidak ditulis.

**Rekomendasi:** gunakan ringkasan session yang diperbarui, entity focus window, atau retrieval khusus dari session history untuk menemukan subject yang disebut sebelum empat turn. Tetap pertahankan guard "jangan menebak" saat ambiguity tidak dapat diselesaikan.

---

## Low

### L1. Word-boundary filter mengorbankan recall untuk singkatan pendek

**Bukti kode:** `services/neo4j_service.py`, `_prepare_search_keyword()`.

Keyword dengan total panjang alfanumerik kurang dari tiga dilewati. Ini memperbaiki false-positive `di`/`an`, tetapi juga berarti entity legitimate seperti `AI`, `UI`, atau `IT` tidak dapat dicari apabila router mengirimnya sendiri.

**Rekomendasi:** gunakan allowlist singkatan yang relevan untuk domain user, atau minta router mengirim frase lebih spesifik seperti `ai engineer`.

---

### L2. Provenance historis tidak dapat direkonstruksi

**Bukti kode:** migrasi runtime di `Neo4jService.__init__()` hanya backfill `fact_id`, timestamp, `is_current`, dan importance.

Fact/node yang sudah ada sebelum provenance ditambahkan tidak memiliki `source_conversation_id` atau `source_message_id`. Kode tidak dapat mengisi nilai tersebut dari graph lama karena sebelumnya memang tidak menyimpan source.

**Rekomendasi:** tampilkan provenance `unknown/legacy` di UI dan jangan menganggap sumber kosong sebagai sumber yang dapat diaudit. Berlaku penuh untuk extraction baru.

---

### L3. Array provenance dan graph response dapat tumbuh tanpa batas

**Bukti kode:** `merge_knowledge()` menambahkan `source_conversation_ids` serta `source_message_ids` ke list property; `get_graph_data()` mengembalikan seluruh list tersebut.

Fact yang sering dikonfirmasi akan terus menambah `source_message_ids`, lalu graph endpoint mengembalikan semua nilai pada setiap visualisasi. Pada skala kecil ini tidak bermasalah, tetapi dapat meningkatkan ukuran node/edge dan payload UI seiring waktu.

**Rekomendasi:** simpan source event pada collection/tabel provenance terpisah, atau batasi array ke N source terbaru sambil menyimpan count dan source pertama/terakhir.

---

## Prioritas Perbaikan yang Disarankan

1. **H1:** ubah pruning agar tidak pernah menghapus graph yang masih memiliki fact aktif.
2. **H2:** tambahkan outbox + retry/replay supaya background failure tidak menyebabkan memory parsial.
3. **H3:** tetapkan semantics delete session dan implementasikan cleanup/retention provenance graph.
4. **H4:** lindungi semua endpoint settings, log, consolidation, dan graph mutation sebelum backend dapat diakses di luar mesin lokal.
5. **M1–M5:** perkuat relevansi retrieval, entity continuity, dan validasi extraction sebelum memperluas volume memory.

## Hal yang Sudah Lebih Baik dari Versi Sebelumnya

- Person tidak lagi dipaksa unique secara global berdasarkan nama.
- Qdrant tidak lagi memakai ID deterministic dari pesan.
- Extraction memiliki konteks sesi dan memblokir kata ganti generik.
- Fact mempunyai `fact_id`, `is_current`, timestamp temporal, serta endpoint edit/delete.
- Neo4j search memakai ranking, current-fact filter, word boundary, dan tidak lagi menaikkan importance ketika read.
- Node/fact baru membawa provenance conversation dan message.
