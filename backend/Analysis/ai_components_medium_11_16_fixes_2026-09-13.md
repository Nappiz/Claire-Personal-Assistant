# Perbaikan M11–M16 — Komponen AI

Tanggal verifikasi: 2026-09-13.

Sumber: [ai_components_extreme_audit_2026-09-12.md](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_components_extreme_audit_2026-09-12.md), bagian M11–M16. Laporan asli dipertahankan sebagai bukti kondisi sebelum perbaikan.

## Status

Seluruh perbaikan M11–M16 telah diimplementasikan. Ruang lingkupnya meliputi recovery vector memory, orchestration tool web, ranking snippet, generation jawaban, serta urutan pesan yang digunakan history dan summary. M17–M18 tidak termasuk permintaan ini.

| ID | Severity audit | Perbaikan | Verifikasi utama |
|---|---|---|---|
| M11 | MEDIUM | Rekonsiliasi setiap event/chunk berdasarkan deterministic ID, payload, fingerprint, dan signature embedding; keyset scan bertahap. | A,X dengan jumlah yang sama tidak menyembunyikan event B yang hilang; projection sesuai tidak di-embed ulang. |
| M12 | MEDIUM | Pisahkan pending URL dari cache hasil; beberapa call ID berbagi satu fetch. | Dua `read_url` identik menghasilkan satu fetch dan dua tool result sukses. |
| M13 | MEDIUM | Pertahankan evidence sukses; error dikembalikan per tool call, dengan kesempatan mengganti URL dalam budget. | Partial search/read tetap menghasilkan jawaban; argumen salah dan URL timeout dapat dipulihkan. |
| M14 | MEDIUM | TF-IDF menjadi sinyal ranking lunak, dengan representasi per query ketika budget cukup. | Snippet Inggris tetap tersedia bagi research goal Bahasa Indonesia meskipun overlap nol. |
| M15 | MEDIUM | Fast path sapaan langsung streaming; gunakan jawaban tanpa tool dari planner tanpa generation kedua. | Sapaan dan jawaban planner yang sah masing-masing memakai satu generation; sapaan bercampur pertanyaan aktual tetap masuk keputusan tool. |
| M16 | MEDIUM | Urutan bersama berdasarkan turn sequence, lalu role; backfill legacy memakai insertion order dan role. | Timestamp identik/clock skew tidak membalik role; summary dan endpoint history memakai aturan yang sama. |

## Detail perbaikan

### M11 — Rekonsiliasi vector memory

Guard berbasis total count sudah dihapus pada pekerjaan sebelumnya. Perbaikan ini melengkapi recovery agar tidak selalu meng-embed ulang seluruh arsip:

- Outbox dipindai dengan keyset pagination, maksimal 100 job per batch. Hanya extraction yang selesai, source message aktif, conversation tanpa tombstone, dan job yang tidak cancelled dipilih. Session database ditutup sebelum pekerjaan embedding.
- Expected projection disusun dari evidence assertion durable yang sama dengan jalur penyimpanan normal. Point ID setiap chunk bersifat deterministic.
- Qdrant dibaca menurut expected point ID, maksimal 64 ID per request. Setiap expected field payload dan fingerprint harus cocok; jumlah point total tidak dipakai untuk membuktikan kelengkapan.
- Fingerprint mencakup teks chunk, provenance, offset, scope, metadata evidence, serta signature embedding. Event yang hilang, chunk yang hilang, isi berubah, atau scope berubah memicu perbaikan.
- Signature mencakup model name, configured revision, dan versi preprocessing/chunking. Retrieval biasa dan candidate retrieval project menolak signature yang tidak sesuai; model berbeda dengan dimensi sama tidak dicampur sebagai ruang embedding yang sama.
- Projection yang sesuai melewati encode. Payload/fingerprint durable menjadi checkpoint per event/chunk: proses berikutnya tetap memeriksa event yang belum lengkap, tanpa bergantung pada cursor global yang bisa melewati failure.
- Chunk obsolete milik event yang sama dibersihkan setelah upsert, atau saat rekonsiliasi projection yang sudah sesuai. Ini juga menyelesaikan kondisi crash setelah upsert tetapi sebelum cleanup.
- Status source diperiksa sebelum dan sesudah external write. Jika source menjadi inactive atau conversation dihapus saat proses berjalan, seluruh chunk pesan sumber ditandai inactive. Pemeriksaan authoritative SQLite pada retrieval tetap berlaku.

Hasil recovery membedakan `eligible`, `indexed`, `skipped`, dan `failed`. Kegagalan satu event tidak menghentikan pemeriksaan event lain.

**Batasan:** rekonsiliasi memvalidasi projection menurut expected source, bukan membuktikan kebenaran semantik setiap vector secara matematis. Orphan dari event lain tidak dihapus berdasarkan count; lifecycle/tombstone dan filter retrieval tetap menjadi pengaman. Jika bobot diganti di bawah model name yang sama, set `EMBEDDING_MODEL_REVISION` ke revision yang benar; perubahan bobot tanpa perubahan identitas konfigurasi tidak dapat diidentifikasi oleh signature ini.

### M12 — URL pending dan completed

Pending request disimpan per normalized URL, dengan daftar call ID yang menunggu. URL kedua yang identik menambahkan call ID ke request pertama; ia tidak mencari halaman yang belum tersedia. Satu outcome sukses maupun error dipasok ke semua call ID yang terkait.

Hasil completed disimpan pada cache terpisah. Pemanggilan ulang URL yang sudah selesai menggunakan hasil cache. Budget pembacaan dihitung dari URL unik yang benar-benar dicoba, termasuk yang gagal; duplicate tidak menghabiskan budget tambahan.

### M13 — Kegagalan sumber parsial

`retrieve_web_context(..., raise_on_error=True)` tetap mengembalikan hasil ketika setidaknya satu query berhasil, disertai warning partial failure. Bila semua query gagal, error service tetap tersedia bagi caller; orchestration chat menangkapnya dan mengembalikan tool result `ok=false`, tanpa mematikan percakapan.

Kegagalan satu halaman tidak membuang halaman lain maupun snippet search. Tool result sukses berisi evidence, sedangkan call gagal berisi error. Argumen salah atau URL di luar hasil search juga dikembalikan sebagai error yang dapat diperbaiki model pada round berikutnya. Model mendapat kesempatan memakai URL alternatif jika masih ada budget URL/round; percobaan tetap dibatasi.

Fallback search juga memakai konteks `unavailable` bila seluruh sumber gagal, sehingga model dapat menyatakan batas evidence. Cancellation tetap diteruskan, tidak diubah menjadi sumber gagal yang boleh diabaikan. Pembatasan URL publik dan allowlist hasil search dipertahankan.

**Batasan:** evidence sukses tidak menjamin cukup untuk menjawab seluruh pertanyaan. Prompt tetap mengharuskan model mengakui kekurangan evidence dan tidak menebak; perbaikan ini mempertahankan kesempatan recovery, bukan menjamin sumber alternatif selalu tersedia.

### M14 — Ranking multilingual

Kandidat dengan cosine TF-IDF nol tetap disimpan dan diberi peringkat di bawah kecocokan leksikal yang lebih kuat. Search result yang sudah lolos validasi URL/schema/engine tidak dinyatakan tidak relevan hanya karena kosakatanya berbeda dari research goal.

Penggabungan mempertahankan satu representative per query sukses jika kuota hasil cukup untuk seluruh query. Sisa kuota mengikuti ranking terhadap research goal; selected results tetap ditampilkan menurut ranking tersebut. Bila budget lebih kecil daripada jumlah query, goal ranking menentukan hasil agar query pertama tidak mendapat prioritas otomatis.

**Batasan:** TF-IDF tetap merupakan ranking leksikal, bukan semantic reranker. Perbaikan menghilangkan hard rejection lintas bahasa dan mempertahankan diversity dalam budget; tidak ada klaim semua kandidat pasti relevan.

### M15 — Generation yang sudah menghasilkan jawaban

Input yang jelas berupa sapaan atau ucapan terima kasih singkat langsung memakai final stream. Fast path harus cocok terhadap seluruh input; “Halo Claire, berapa harga emas hari ini?” tidak melewati keputusan tool.

Untuk turn lain, jika planner menghasilkan jawaban nonkosong tanpa tool call, tanpa refusal, dan tidak berhenti karena `length`, teks tersebut diteruskan verbatim dengan usage yang sudah tercatat. Jawaban tidak dibuang lalu dihasilkan ulang. Budget output planner kini sama dengan budget jawaban karena request tersebut juga dapat menjadi jawaban akhir.

Round yang benar-benar menggunakan tool tetap mengikuti orchestration search/read sebelum jawaban, termasuk metadata provider yang sudah dipertahankan oleh serializer. Empty/invalid response tetap menggunakan recovery yang tersedia.

**Batasan:** sapaan langsung streaming, tetapi jawaban tanpa tool dari planner umum diteruskan setelah completion nonstream selesai. Alur tool belum diubah menjadi satu streaming request dengan tool accumulation; tidak ada klaim seluruh time-to-first-token atau seluruh biaya internal sudah dioptimalkan. Router/extractor/title merupakan panggilan dengan tujuan berbeda dan tidak dihapus oleh perbaikan ini.

### M16 — Urutan pesan durable

`Message.chronological_order()` menjadi aturan bersama bagi short-term history, compaction summary, dan endpoint history. Urutan utama adalah `turn_sequence`; role user mendahului assistant di dalam turn, lalu timestamp dan ID menjadi tie-breaker tambahan. Pengambilan latest N memakai kebalikan aturan yang sama dan dibalik kembali untuk prompt.

Backfill SQLite untuk row legacy yang belum memiliki sequence memakai `created_at` dan `rowid` untuk mempertahankan insertion order saat timestamp sama. Pairing mengikuti role: assistant menutup turn, sementara user berikutnya memulai turn baru bila user sebelumnya belum mendapatkan assistant. Pairing tidak lagi menganggap setiap dua row pasti satu pasangan dan tidak memakai urutan UUID sebagai kronologi.

**Batasan:** backfill hanya mengisi sequence yang masih NULL. Sequence durable yang sudah ada tidak diubah otomatis. Row historis yang metadata urutannya sudah salah atau hilang tidak selalu dapat direkonstruksi dengan pasti; perbaikan ini tidak mengklaim memulihkan seluruh korupsi historis tanpa evidence tambahan.

## Hasil pengujian

- **117 unittest backend lulus**, termasuk **22 pengujian baru** M11–M16 dan regresi sebelumnya.
- Qdrant in-memory nyata: count sama dengan missing event, projection yang sudah sesuai, perubahan scope/isi, perubahan model/revision berdimensi sama, missing chunk, obsolete chunk, dan resume cleanup.
- SQLite sementara nyata: keyset scan 205 job, reindex outbox dua kali tanpa duplicate encode, deletion saat write, timestamp identik/clock skew, ordering summary, backfill dengan UUID yang urutannya berbeda dari insertion, dan user turn tanpa jawaban.
- Mock HTTP/provider: partial search pada strict mode, partial read, duplicate URL, koreksi argumen, URL pengganti setelah timeout, all-source failure, lintas bahasa, satu generation untuk sapaan, reuse jawaban planner, serta sapaan yang mengandung pertanyaan publik aktual.
- **Embedding E5 nyata, 1.024 dimensi:** A,X dengan count dua berhasil direkonsiliasi menuju expected A,B; B dibuat, dua projection sesuai dilewati, dan hanya satu pemanggilan encoder terjadi selama rekonsiliasi. Memori pengguna tidak ditulis.

Perintah dari direktori backend:

```powershell
& '.\venv\Scripts\python.exe' -m unittest discover -s tests -q
& '.\venv\Scripts\python.exe' Analysis/ai_medium_11_16_embedding_live_checks.py
```

Script embedding membutuhkan bobot model lokal yang sudah tersedia dan memakai Qdrant in-memory. Tidak memanggil API provider atau mengakses arsip SQLite pengguna. Tidak dilakukan benchmark latensi produksi atau pengujian outage situs publik secara langsung; kegagalan eksternal diuji deterministik melalui mock.

## Pengoperasian dan file

Restart backend untuk memakai perbaikan dan menjalankan startup reconciliation yang sudah tersedia. Vector tanpa signature baru tidak dipakai sebagai evidence sampai berhasil direkonsiliasi. Job aktif yang projection-nya sudah sesuai akan dilewati pada restart berikutnya; kegagalan tetap tercatat dan dapat dicoba kembali. Raw chat tetap berada di SQLite.

`EMBEDDING_MODEL_REVISION` ditambahkan pada settings dan `.env.example`, lalu diteruskan ke loader ketika diisi. Saat mengganti model dengan dimensi berbeda, gunakan koleksi versioned baru sesuai validasi koleksi yang sudah ada. Tidak ada migrasi Alembic baru; field lifecycle/turn dari perbaikan HIGH tetap dipakai.

File implementasi: `services/qdrant_service.py`, `services/memory_service.py`, `services/web_search_service.py`, `services/llm_service.py`, `models/message.py`, `routes/chat_routes.py`, `main.py`, `configs/settings.py`, dan `.env.example`.

Pengujian: [test_extreme_medium_11_16_ai_fixes.py](D:/Nafiz/Career/Project/personal-assistant/backend/tests/test_extreme_medium_11_16_ai_fixes.py). Integrasi embedding: [ai_medium_11_16_embedding_live_checks.py](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_medium_11_16_embedding_live_checks.py).
