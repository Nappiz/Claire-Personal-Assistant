# Perbaikan M01–M10 — Audit Komponen AI

Tanggal verifikasi: 2026-09-13.

Sumber: [ai_components_extreme_audit_2026-09-12.md](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_components_extreme_audit_2026-09-12.md), bagian M01–M10. Laporan audit asli dipertahankan sebagai catatan kondisi sebelum perbaikan.

## Status dan ruang lingkup

Perbaikan seluruh temuan M01–M10 telah diimplementasikan pada streaming, ekstraksi fakta, resolusi scope, graph memory, dan vector memory. Perbaikan H01–H12 tetap tercakup oleh pengujian regresi sebelumnya. M11 dan temuan di luar daftar permintaan tidak termasuk pekerjaan ini.

| ID | Severity audit | Perubahan | Verifikasi |
|---|---|---|---|
| M01 | MEDIUM | Semua delta string tidak kosong diteruskan utuh. | Spasi dan newline dari chunk terpisah dipertahankan persis. |
| M02 | MEDIUM | Skip extraction mempertimbangkan klausa deklaratif dalam turn pertanyaan. | Tujuh contoh fakta eksplisit mencapai extractor. |
| M03 | MEDIUM | Qdrant hanya mengindeks evidence assertion positif hasil ekstraksi, dengan metadata rujukan dan modalitas. | Graph kosong tidak menghasilkan vector assertion; caller tanpa evidence ditolak. |
| M04 | MEDIUM | Chunking mengikuti tokenizer encoder, overlap, offset, dan batch embedding. | Fast/slow tokenizer diuji; E5 nyata berhasil mengambil fakta setelah token 512. |
| M05 | MEDIUM | Kandidat diambil melalui indeks, satu query untuk seluruh keyword, traversal dan ranking gabungan. | Pengujian regresi dan eksekusi Neo4j nyata berhasil. |
| M06 | MEDIUM | Envelope asli wajib valid sebelum sanitasi; output rusak menjadi kegagalan yang dapat di-retry. | Root/field salah ditolak; retry memori tetap dapat menyimpan vector. |
| M07 | MEDIUM | Konsep project dibedakan dari project milik user; izin web mengikuti intent publik. | Pertanyaan project management dan harga Pertamax tidak diblokir oleh scope/hit. |
| M08 | MEDIUM | Hanya identitas active project yang cocok secara eksplisit memakai key project aktif. | Atlas → Boreal mempertahankan dua endpoint, termasuk saat retrieval scoped. |
| M09 | MEDIUM | Registry linking, canonical context, alias, reuse ID legacy, dan karantina ambigu. | Parafrasa, node legacy, ambiguity, deletion, serta cleanup provenance lulus. |
| M10 | MEDIUM | Inisialisasi embedding memakai lock dan cooldown retry; bobot valid dipertahankan saat store gagal. | Retry setelah cooldown berhasil; kegagalan store tidak memuat ulang model. |

## Detail per temuan

### M01 — Delta whitespace

Filter pengiriman delta tidak lagi memakai `content.strip()`. Pemeriksaan tersebut hanya dipakai untuk mendeteksi apakah provider pernah mengirim teks yang terlihat, tanpa mengubah teks jawaban. Route chat menyusun jawaban dengan `"".join(reply_parts)` sehingga whitespace yang diteruskan tetap tersimpan.

Uji penerimaan: `hello`, ` `, `world`, `\n`, `next` menghasilkan tepat `hello world\nnext`.

### M02 — Fakta dalam pertanyaan

Deteksi per klausa berjalan sebelum skip recall-only. Klausa deklaratif dalam input campuran dan fakta yang dibungkus pertanyaan seperti “Apa kamu tahu golongan darahku O?” tetap dikirim ke extractor. Kata tanya di dalam nama atau klausa lain tidak otomatis membatalkan seluruh turn. Extractor menentukan apakah kandidat klausa benar-benar merupakan assertion; prompt membedakan assertion, pertanyaan, kutipan, dan hipotesis.

Uji penerimaan mencakup tiga contoh laporan asli, assertion setelah pertanyaan, pertanyaan metakognitif, assertion bertanda tanya, dan nama startup yang mengandung “Apa”. Pertanyaan recall murni tetap tercakup oleh pengujian sebelumnya.

### M03 — Evidence assertion dan arsip percakapan

Pesan asli tetap menjadi arsip SQLite. Jalur indexing memori menyusun evidence dari edge positif yang sudah lolos validasi, dengan source/target yang di-resolve dan confidence yang memenuhi threshold. Pertanyaan tanpa fakta, output kosong, retraction-only, dan edge pengelompokan `BELONGS_TO` tidak menjadi assertion vector.

Evidence menyimpan source message, role, modality, polarity, rujukan entitas, relasi, serta offset span. Qdrant menolak pemanggilan yang tidak menyertakan klasifikasi assertion dan evidence yang sesuai teks. Retrieval mensyaratkan `evidence_version=2`; vector lama yang berisi raw question tidak ikut menjadi bukti faktual.

**Batasan:** span yang disimpan menunjuk teks evidence yang dinormalisasi dari graph, bukan kutipan verbatim dengan offset ke pesan mentah. Hubungan ke pesan sumber tetap tersedia melalui message ID. Kebenaran semantik output extractor tetap bergantung pada model; validasi schema tidak membuktikan bahwa setiap assertion benar.

### M04 — Chunking pesan panjang

Encoder diinisialisasi sebelum chunking agar tokenizer dan `max_seq_length` yang dipakai benar-benar milik model aktif. Fast tokenizer memakai offset token; slow tokenizer memakai penghitungan token aktual. Setiap chunk diperiksa terhadap batas encoder, termasuk prefix E5 dan special tokens, sehingga fallback tidak mengandalkan estimasi karakter yang dapat terpotong diam-diam.

Chunk memakai overlap, deterministic point ID, message/event ID, dan offset. Embedding diproses dalam batch dengan ukuran internal maksimal 16. Payload hanya menyimpan teks chunk dan evidence yang beririsan dengannya. Retrieval memilih chunk relevan dan melakukan deduplikasi per pesan, sehingga satu dokumen tidak menghabiskan seluruh kuota hasil.

Verifikasi E5 nyata: input 1.409 token menghasilkan empat chunk; chunk terbesar dengan prefix/special tokens berukuran 444 token, di bawah window 512. Uji terpisah E5 + Qdrant in-memory menempatkan fakta PostgreSQL setelah token 700; fakta tersebut berhasil diambil, dengan satu hasil setelah deduplikasi dan similarity sekitar 0,831. Pengujian tidak menulis koleksi memori pengguna.

### M05 — Retrieval graph

Startup menambahkan range index nama dan full-text index nama/identity context. Retrieval membangun satu query untuk semua keyword, menggabungkan kandidat full-text dan nama eksak, membatasi kandidat menjadi 64, lalu menelusuri relasi di sekitarnya. Relasi dideduplikasi sebelum ranking; hasil global dibatasi menjadi 20.

Ranking mengutamakan kecocokan entitas sekaligus relasi, lalu coverage keyword, scope, relevansi kandidat, importance, dan recency. Scope ditentukan oleh fakta, sehingga endpoint project eksternal tidak menjadi tidak terlihat hanya karena bukan anggota project aktif. Arah relasi asli dipertahankan meskipun traversal kandidat berjalan dari kedua endpoint.

Uji Neo4j nyata membuktikan fakta `WORKS_AT` yang relevan tetap menjadi hasil pertama meskipun ada delapan fakta lain dari subject yang sama dengan importance sangat tinggi. Query scoped juga mengembalikan dependensi project aktif menuju project eksternal.

**Batasan:** budget kandidat dan hasil tetap dapat membatasi recall pada graph sangat padat. Tidak ada klaim angka peningkatan latensi produksi atau benchmark skala besar.

### M06 — Schema ekstraksi dan retry

JSON harus berupa object dengan field `nodes` dan `edges` berupa array object. `retractions`, bila tersedia, juga harus berupa array object. Validasi dilakukan pada envelope asli sebelum default/sanitasi dapat mengubah output rusak menjadi graph kosong. Code fence JSON yang membungkus seluruh respons boleh dibuka; pencarian substring object di dalam respons rusak tidak lagi digunakan.

Output `{"nodes": [], "edges": []}` merupakan hasil tanpa fakta yang sah. Root array, object tanpa field wajib, field bertipe salah, dan anggota array non-object menghasilkan error. Outbox mempertahankan tahap vector sebagai pending ketika extraction gagal, sehingga retry extraction berikutnya masih bisa mengindeks fakta yang ditemukan.

### M07 — Scope project dan informasi publik

Kata `project/proyek/projek` sendiri tidak lagi menjadi bukti rujukan project milik user. Penyebutan nama project eksplisit dan rujukan kepemilikan/deiktik seperti “proyekku” atau “project ini” tetap masuk resolusi scope. Jalur fallback saat timeout/error resolver memakai pembedaan yang sama.

Kehadiran vector hit scoped tidak otomatis mematikan web. Intent konsep, dokumentasi, perbandingan, rekomendasi, pencarian eksplisit, serta informasi publik terkini tetap dapat memakai web di project session. Detail internal project dan scope yang benar-benar ambigu tetap mengikuti pembatasan yang sudah ada.

Uji penerimaan mencakup konsep project management, harga Pertamax hari ini dengan memory hit, dan dokumentasi AWS terbaru di project Atlas.

### M08 — Identitas project eksternal

Extractor tidak lagi mengganti node Project pertama menjadi project aktif. Ia mencari kecocokan eksplisit terhadap project ID/nama; bila tidak ada, node aktif ditambahkan tanpa mengganti node eksternal. Graph merge memakai aturan yang sama. Relasi `BELONGS_TO` yang sudah mengaitkan entitas dengan project tertentu dipertahankan.

Fakta dapat berscope Atlas sambil menyebut Boreal sebagai identitas berbeda. Uji extractor, graph recorder, dan transaksi Neo4j nyata memastikan tidak terjadi self-loop akibat penggabungan dua Project.

### M09 — Registry identitas Person

Canonical context menormalkan parafrasa relasional yang dikenal, termasuk “ibu nafiz”, “ibu dari nafiz”, dan “mother of nafiz”, sambil mempertahankan atribut pembeda. Nama sama dengan konteks orang berbeda tetap menghasilkan identitas berbeda.

`EntityIdentity` menyimpan keputusan linking melalui `RESOLVES_TO`. Unique constraint dan write fence menyerialkan keputusan untuk identitas yang sama. Jika registry belum terhubung, candidate lookup berdasarkan nama mencari node legacy dengan canonical context yang cocok; satu kandidat memakai ID yang sudah ada. Banyak kandidat cocok atau pencarian mencapai batas 51 kandidat menghasilkan karantina, bukan penggabungan otomatis. Evidence vector sumber ambigu ikut diinvalidasi.

Node menyimpan signature dan alias konteks. Linking registry tetap mengikuti node ketika key/display metadata diedit. Penghapusan, cleanup provenance, konsolidasi, dan statistik memperlakukan hubungan registry secara terpisah dari fakta pengguna.

**Batasan:** canonicalization bersifat konservatif, bukan penyelesaian seluruh parafrasa semantik. Duplikat historis yang ambigu tidak digabung atau dihapus otomatis; registry menandainya untuk pemeriksaan. Deskripsi baru yang tidak dapat dibuktikan setara tetap membutuhkan evidence identitas yang lebih jelas.

### M10 — Pemulihan embedding

Kegagalan pertama tidak lagi melatch encoder sampai restart. Setelah cooldown, request berikutnya mencoba inisialisasi kembali; lock memastikan hanya satu percobaan berjalan. Default backoff meningkat dari 2 detik hingga maksimum 60 detik, dikonfigurasi melalui environment. Reset/warmup eksplisit tersedia untuk keadaan gagal, tanpa mereset encoder sehat yang sedang dipakai.

Jika bobot model berhasil dimuat tetapi kesiapan koleksi Qdrant gagal, bobot disimpan sebagai pending encoder dan dipakai ulang pada retry. Keadaan sukses membersihkan error dan counter. Error tetap dilaporkan selama penyebab belum pulih; tidak dibuat embedding palsu sebagai fallback.

## Hasil verifikasi

- **95 unittest backend lulus**, termasuk 18 pengujian baru M01–M10 serta regresi perbaikan sebelumnya.
- **Integrasi Neo4j nyata lulus:** endpoint project, retrieval scoped, registry parafrasa, reuse node legacy, deletion registry, karantina ambigu, ranking entitas/relasi, dan cleanup provenance. Semua write data uji di-rollback; hanya indeks/constraint startup dibuat secara idempotent.
- **Embedding nyata lulus:** tokenizer E5 tidak melampaui window; retrieval fakta di ekor panjang berhasil menggunakan Qdrant in-memory.
- Route penyimpanan jawaban diperiksa dan tetap menyusun delta tanpa trim.

Perintah regresi dari direktori backend:

```powershell
& '.\venv\Scripts\python.exe' -m unittest discover -s tests -q
& '.\venv\Scripts\python.exe' Analysis/ai_medium_01_10_live_checks.py
```

Script integrasi membutuhkan Neo4j lokal. Ia tidak memanggil LLM atau menulis Qdrant. Probe audit lama sengaja menguji adanya kerentanan sebelum perbaikan; hasilnya bukan kriteria keberhasilan implementasi baru.

## Perubahan data dan pengoperasian

1. Restart backend untuk memakai kode baru dan menjalankan pembuatan indeks/constraint Neo4j yang idempotent.
2. Startup reindex yang sudah tersedia membangun evidence vector versi 2 dari `extracted_knowledge` durable dalam outbox, untuk pesan aktif pada percakapan yang belum dihapus. Pesan tanpa assertion yang memenuhi syarat dilewati.
3. Vector lama tanpa `evidence_version=2` dikecualikan dari retrieval. Jika reindex gagal atau extraction historis belum tersedia, evidence tersebut belum dapat diretrieve sampai pemrosesan berhasil; raw history tetap ada di SQLite.
4. Tidak ada migrasi SQLite baru untuk M01–M10. Registry dan indeks baru berada di Neo4j; metadata chunk/evidence berada di Qdrant.
5. Dependency Windows `pywin32` dicantumkan eksplisit; parameter retry embedding didokumentasikan di `.env.example`.

File utama: `services/llm_service.py`, `services/memory_service.py`, `services/qdrant_service.py`, `services/neo4j_service.py`, `configs/settings.py`, `.env.example`, dan `requirements.txt`. Pengujian baru berada pada [test_extreme_medium_ai_fixes.py](D:/Nafiz/Career/Project/personal-assistant/backend/tests/test_extreme_medium_ai_fixes.py); verifikasi integrasi berada pada [ai_medium_01_10_live_checks.py](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_medium_01_10_live_checks.py).
