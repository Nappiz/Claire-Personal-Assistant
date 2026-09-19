# Audit kritis komponen AI — Claire / Personia

**Tanggal:** 12 September 2026  
**Workspace:** `D:/Nafiz/Career/Project/personal-assistant`  
**Jenis pekerjaan:** audit dan reproduksi; tidak memperbaiki kode aplikasi.

## 1. Kesimpulan dan batas penilaian

Ditemukan **31 masalah: 12 HIGH, 18 MEDIUM, dan 1 LOW**. Kegagalan terpenting berada pada konsistensi memori, hubungan antara kegagalan subsistem dengan jawaban chat, dan pengendalian pekerjaan yang berjalan bersamaan. Validasi JSON dan keberadaan outbox belum menjamin bahwa fakta yang digunakan AI benar, terbaru, tersimpan tepat satu kali, atau benar-benar hilang setelah dihapus.

**66 tes bawaan lulus dalam lingkungan terisolasi. Sebanyak 23 probe tambahan juga lulus dengan assertion yang membuktikan perilaku bermasalah saat ini.** Lulusnya probe audit berarti celah berhasil direproduksi, bukan aplikasi sudah benar. Hasil ini tidak digunakan untuk mengklaim tingkat kegagalan produksi atau probabilitas halusinasi tertentu.

Tidak ada bukti yang cukup untuk menaikkan temuan menjadi kerusakan menyeluruh yang tidak dapat dipulihkan atau kompromi sistem berskala besar. Kategori severity yang tidak mempunyai temuan tidak ditampilkan.

### 1.1 Scope yang diperiksa

| Komponen | Cakupan pemeriksaan |
|---|---|
| Orkestrasi AI | `/chat`, `/chat/stream`, pemilihan provider, pemanggilan model, tool loop, pemulihan error |
| Konteks percakapan | prompt, riwayat 30 pesan, ringkasan berjalan, resolusi rujukan dan waktu |
| Memori AI | ekstraksi, kebijakan relasi, outbox, retry, pembatalan, provenance, koreksi dan penghapusan |
| Retrieval | pencarian semantik Qdrant, query Neo4j, prioritas project, pencarian web dan pembacaan halaman |
| Frontend terkait AI | konsumsi stream, stop, failover model, penanganan terminal event |
| Operasional AI | timeout, pekerjaan maintenance/reindex, penggunaan token, pengujian terkait |

Autentikasi umum, CORS, keamanan deployment publik, styling, fitur pin, CRUD yang tidak berhubungan dengan AI, dan kualitas kode umum **tidak dijadikan temuan**. Salah satu dari 66 tes bawaan kebetulan menguji pin sesi; itu hanya bagian dari penjalanan suite yang sudah ada, bukan perluasan scope audit.

### 1.2 Metode dan kekuatan bukti

- **Reproduksi terisolasi:** menjalankan fungsi aplikasi dengan SQLite sementara dan respons sintetis; transport Neo4j dan model diganti mock. Untuk skenario balapan penghapusan, penjadwalan I/O eksternal dikendalikan secara deterministik. Untuk ringkasan, digunakan dua thread dan barrier.
- **Bukti statis:** alur panggilan, schema, kondisi, dan query yang dapat ditelusuri langsung. Temuan ini tidak diklaim telah dieksekusi pada Neo4j asli.
- **Bukti dependensi:** memeriksa SDK yang terpasang dan dokumentasi primer untuk semantik transaksi, timeout, serta batas embedding.
- Database aplikasi, graph produksi, isi percakapan pribadi, dan API model berbayar tidak dipakai sebagai bahan eksperimen. Kredensial asli tidak ditampilkan. Pengujian tidak menjalankan aplikasi web atau lifespan terhadap database aplikasi.
- Tidak dilakukan benchmark p95/p99, evaluasi stokastik model, serangan prompt injection pada model hidup, ataupun `EXPLAIN/PROFILE` pada Neo4j hidup. Karena itu, laporan tidak mengarang angka latensi, rasio halusinasi, atau keberhasilan eksploitasi.
- Dokumen audit lama hanya dipakai sebagai pemeriksaan silang setelah pembacaan kode. Nomor baris dan status masalah dinilai dari kode saat audit ini, bukan disalin dari laporan lama.

**Definisi severity:** HIGH berarti ada jalur realistis yang merusak integritas/kelangsungan memori atau ketersediaan fungsi AI inti; MEDIUM berarti gangguan nyata yang dibatasi jenis input, tahap, atau kondisi tertentu; LOW berarti dampak terbatas pada observabilitas atau pengoperasian. Besarnya severity tidak menyatakan frekuensi kejadian yang sudah terukur.

### 1.3 Daftar temuan

| ID | Severity | Masalah |
|---|---|---|
| H01 | HIGH | Retry memori sinkron memblokir event loop seluruh API |
| H02 | HIGH | Batas waktu retrieval tidak mencakup router dan scope resolution |
| H03 | HIGH | Kegagalan memori menghapus jawaban sukses dan membatalkan retry |
| H04 | HIGH | Worker dapat mengambil job yang sedang diproses tanpa fencing |
| H05 | HIGH | Write yang terlambat dapat menghidupkan memori setelah penghapusan |
| H06 | HIGH | Koreksi graph dan pemeriksaan konflik tidak atomik |
| H07 | HIGH | Retry memakai waktu pemrosesan dan dapat mengaktifkan fakta lama |
| H08 | HIGH | Kontrak ekstraksi tidak dapat mencabut fakta tanpa pengganti sejenis |
| H09 | HIGH | Fakta usang tetap masuk prompt melalui memori vektor |
| H10 | HIGH | Ringkasan kehilangan pembaruan dan pesan tanpa checkpoint |
| H11 | HIGH | Turn tidak mempunyai identitas durable untuk stop, retry, dan concurrency |
| H12 | HIGH | Context window dibatasi jumlah pesan, bukan anggaran token |
| M01 | MEDIUM | Stream membuang spasi dan newline yang bermakna |
| M02 | MEDIUM | Regex pertanyaan melewatkan fakta eksplisit |
| M03 | MEDIUM | Semua ucapan user dilabeli sebagai assertion |
| M04 | MEDIUM | Satu embedding per pesan mengabaikan ekor pesan panjang |
| M05 | MEDIUM | Query graph berulang memindai kandidat luas dan memangkas konteks yang benar |
| M06 | MEDIUM | Output ekstraksi tanpa schema yang diminta dianggap sukses kosong |
| M07 | MEDIUM | Heuristik project memblokir pertanyaan publik dan web yang diperlukan |
| M08 | MEDIUM | Semua entitas Project digabung ke project aktif |
| M09 | MEDIUM | Parafrasa identitas memecah orang yang sama menjadi beberapa node |
| M10 | MEDIUM | Satu kegagalan inisialisasi mematikan embedding sampai restart |
| M11 | MEDIUM | Reindex menganggap jumlah vektor sebagai bukti kelengkapan |
| M12 | MEDIUM | Dua read_url identik dalam satu batch menyebabkan StopIteration |
| M13 | MEDIUM | Satu sumber web gagal menggagalkan hasil lain yang berhasil |
| M14 | MEDIUM | Filter TF-IDF membuang bukti relevan lintas bahasa |
| M15 | MEDIUM | Chat sederhana memanggil model dua kali sebelum selesai |
| M16 | MEDIUM | Timestamp sama dapat membalik urutan user dan assistant |
| M17 | MEDIUM | Query memori tidak menerima konteks untuk meresolusikan rujukan |
| M18 | MEDIUM | Jawaban terpotong batas token tetap dinyatakan selesai |
| L01 | LOW | Pelaporan token melewatkan pemanggilan AI internal dan turn gagal |

## 2. HIGH

### H01 — Retry memori sinkron memblokir event loop seluruh API

**Bukti:** [main.py:135](D:/Nafiz/Career/Project/personal-assistant/backend/main.py:135) memanggil `process_due_memory_jobs(limit=25)` langsung dari coroutine. [memory_service.py:722](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:722) memproses job berurutan; tahap ekstraksi menggunakan SDK model sinkron. `memory_maintenance_task` juga menjalankan Cypher sinkron dari coroutine di [main.py:119](D:/Nafiz/Career/Project/personal-assistant/backend/main.py:119).

**Pemicu:** ada job pending/failed setelah restart atau setelah interval retry, lalu provider lambat atau embedding/graph membutuhkan waktu lama.

**Masalah dan dampak:** deklarasi `async def` tidak membuat pemanggilan di dalamnya nonblocking. Selama job diproses, event loop tidak dapat mengirim delta stream, melayani request lain, atau memproses pembatalan secara normal. Satu kegagalan provider pada jalur maintenance dapat membekukan chat yang memakai provider lain sekalipun. Pemanggilan `create_task` saat startup tidak mengisolasi pekerjaan sinkron ini.

**Dasar HIGH:** kegagalan terlokalisasi di satu job meluas menjadi ketidaktersediaan API pada worker yang sama.

**Saran:** jalankan pekerjaan di worker terpisah atau `await asyncio.to_thread(...)` dengan concurrency terbatas; jangan memindahkan loop tanpa batas ke thread baru untuk setiap tick. Tetapkan deadline job, lease/fencing, dan penghentian worker yang jelas. Maintenance graph harus mengikuti prinsip yang sama.

**Validasi:** bukti statis. Tes penerimaan: tahan satu pemanggilan ekstraksi sintetis selama beberapa detik dan pastikan stream/request lain tetap maju selama penahanan tersebut.

### H02 — Batas waktu retrieval tidak mencakup router dan scope resolution

**Bukti:** [memory_service.py:261](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:261) menjalankan resolusi project, lalu router pada baris 277, **sebelum** batas waktu future Qdrant/Neo4j pada baris 337. Resolusi semantik project memanggil embedding langsung pada baris 186. [llm_service.py:60](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:60) membuat client sinkron tanpa `timeout` atau `max_retries`, berbeda dari client async.

**Pemicu:** provider router tidak responsif, cold start embedding saat project ambigu, atau backend retrieval terus macet pada banyak request.

**Masalah dan dampak:** pengaturan retrieval enam detik bukan deadline keseluruhan. Probe client aktual menemukan `timeout.read=600` detik dan `max_retries=2`, bukan pengaturan aplikasi 90 detik. Ini konsisten dengan [SDK OpenAI](https://github.com/openai/openai-python#timeouts). Jangan menafsirkan angka ini sebagai satu deadline total yang pasti: timeout SDK bekerja per operasi dan retry menambah durasi.

Setelah timeout future, `cancel()` tidak menghentikan fungsi yang sudah berjalan. `shutdown(wait=False)` mengembalikan kontrol tetapi worker masih bekerja. Pool baru dibuat per request sehingga stall berulang dapat menumpuk thread dan pekerjaan tertinggal.

**Dasar HIGH:** ketergantungan router memblokir jalur semua request yang melewatinya, sementara proteksi timeout memberi cakupan yang lebih sempit dari yang diperlukan.

**Saran:** budget end-to-end untuk scope resolution, router, embedding, graph, dan model; timeout/retry khusus untuk LLM internal; circuit breaker; pool bersama yang dibatasi; batas waktu pada query/transport, bukan hanya penantian future. Izinkan fallback lokal ketika router melewati budget.

**Validasi:** timeout client direproduksi oleh `test_sync_client_ignores_configured_llm_timeout`; cakupan deadline dan worker tertinggal dibuktikan statis.

### H03 — Kegagalan memori menghapus jawaban sukses dan membatalkan retry

**Bukti:** [chat_routes.py:353](D:/Nafiz/Career/Project/personal-assistant/backend/routes/chat_routes.py:353) mengaktifkan strict retrieval. Setelah jawaban selesai di-stream, baris 393–423 menunggu seluruh `save_interaction(..., report_errors=True)` dan mengubah kegagalan memori menjadi error terminal. [memory_service.py:1031](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:1031) mengganti isi jawaban tersimpan dengan analisis error; baris 1036–1040 membatalkan job yang belum selesai. [page.tsx:435](D:/Nafiz/Career/Project/personal-assistant/frontend/app/chat/page.tsx:435) juga mengganti jawaban di UI.

**Pemicu:** respons model sudah baik, tetapi ekstraksi gagal validasi, vector write gagal, atau graph sementara tidak tersedia. Pada retrieval, satu backend gagal walaupun backend lain berhasil juga cukup untuk membatalkan turn.

**Masalah dan dampak:** kegagalan fitur memori diperlakukan sebagai kegagalan jawaban. User kehilangan jawaban asli, user turn ditandai `failed_turn` dan dikeluarkan dari history normal. Job durable yang seharusnya dapat dicoba ulang malah menjadi `cancelled`. Jika vector sudah tersimpan sebelum graph gagal, data eksternal tersebut tidak di-rollback meskipun turn dikeluarkan dari konteks percakapan.

**Dasar HIGH:** satu gangguan subsistem menyebabkan hilangnya jawaban yang valid dan pemulihan memori tidak berjalan. Ini perilaku yang sengaja dikodekan, tetapi konsekuensi availability dan integritasnya tetap nyata.

**Saran:** commit chat sebagai unit mandiri; laporkan `memory_pending`/`memory_degraded` tanpa menimpa jawabannya; pertahankan outbox retryable. Analisis error menjadi metadata/diagnostik terpisah. Bedakan kegagalan total retrieval dari kegagalan satu sumber; berikan status degradasi kepada model agar tidak menebak fakta yang tidak tersedia.

**Validasi:** tes bawaan `test_internal_memory_failure_replaces_done_with_diagnostic_event` justru mengunci perilaku terminal tersebut. Penimpaan isi SQLite dan pembatalan job ditelusuri langsung dari kode.

### H04 — Worker dapat mengambil job yang sedang diproses tanpa fencing

**Bukti:** [memory_service.py:570](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:570) membaca job, hanya menolak `completed`/`cancelled`, lalu mengubah status menjadi `processing`. Tidak ada conditional update, owner token, atau pemeriksaan lease dalam fungsi ini. Endpoint retry dapat mengubah job `processing` menjadi `pending` pada baris 757–763. `_update_memory_job` pada baris 492 tidak mengecek kepemilikan worker.

**Pemicu:** request retry bersamaan, scheduler mengambil job pending ketika jalur chat hendak memprosesnya, atau lease lima menit habis saat panggilan sinkron belum selesai.

**Masalah dan dampak:** dua worker dapat mengekstrak dan menulis job yang sama. Upsert Qdrant memakai point ID stabil, tetapi ekstraksi dapat berbeda antarpercobaan dan graph melakukan penguatan importance serta timestamp setiap kali. Worker lama juga dapat menulis hasil setelah worker baru atau pembatalan berjalan.

**Dasar HIGH:** mekanisme pengiriman pekerjaan belum menjamin satu pemilik aktif dan efek graph belum idempoten; ini dapat merusak state memori tanpa error eksplisit.

**Saran:** claim melalui `UPDATE ... WHERE eligible AND lease_expired ... RETURNING`; simpan owner/fencing token dan deadline lease; semua update tahap harus mengecek token tersebut. Jangan izinkan manual retry mengambil alih lease yang masih valid. Gunakan ID event stabil untuk deduplikasi efek di graph.

**Validasi:** `test_processing_job_can_be_claimed_again` membuktikan job yang masih `processing` diproses lagi hingga selesai, bahkan tanpa menunggu lease kedaluwarsa.

### H05 — Write yang terlambat dapat menghidupkan memori setelah penghapusan

**Bukti:** [memory_service.py:634](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:634) mengecek status sebelum `save_memory`, bukan secara atomik bersama write. [chat_routes.py:635](D:/Nafiz/Career/Project/personal-assistant/backend/routes/chat_routes.py:635) membatalkan job, menghapus graph dan vector, lalu menghapus record SQLite. Reindex pada [memory_service.py:1097](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:1097) bahkan menulis dari snapshot tanpa pemeriksaan ulang apakah sumber masih ada.

**Pemicu dan urutan yang valid:**

1. Worker melewati `_memory_job_is_active` dan tertahan di embedding/upsert.
2. Penghapusan membatalkan job, menyelesaikan delete eksternal, lalu menghapus conversation/outbox.
3. Write worker selesai setelah delete terakhir.

**Masalah dan dampak:** memori muncul kembali setelah API mengatakan penghapusan berhasil. Menghapus vector terakhir tidak membuktikan semua write sebelumnya telah selesai. `_update_memory_job` kemudian boleh mengembalikan `None`, tetapi vector yang telanjur tertulis tidak dibersihkan.

**Dasar HIGH:** semantik lupa/penghapusan memori gagal; setelah sumber dan provenance di SQLite dihapus, penanganan orphan menjadi lebih sulit.

**Saran:** tombstone durable per conversation, fencing semua writer termasuk reindex, pembatalan dan drain worker, serta cleanup idempoten yang dapat diulang. Sebagai pertahanan tambahan, retrieval harus menolak memori dari sumber bertombstone sebelum memasukkannya ke prompt. Tombstone jangan langsung dihapus bersama outbox.

**Validasi:** `test_vector_write_can_finish_after_session_deletion` mereproduksi penjadwalan ini dengan SQLite asli sementara dan vector store sintetis. Eksperimen ini membuktikan celah koordinasi; bukan klaim pengujian konkurensi server Qdrant asli.

### H06 — Koreksi graph dan pemeriksaan konflik tidak atomik

**Bukti:** [neo4j_service.py:309](D:/Nafiz/Career/Project/personal-assistant/backend/services/neo4j_service.py:309) membaca konflik, baris 402 menulis fakta baru, dan baris 430/451 menonaktifkan fakta lama melalui `session.run` terpisah. Node juga ditulis satu per satu. SDK terpasang dan [dokumentasi Neo4j](https://neo4j.com/docs/api/python-driver/current/api.html) menyatakan `Session.run` merupakan transaksi auto-commit; satu session bukan satu transaksi untuk seluruh batch.

**Pemicu:** proses berhenti setelah fakta baru di-commit tetapi sebelum fakta lama dinonaktifkan; atau dua koreksi single-valued membaca snapshot tanpa konflik yang sama sebelum keduanya menulis.

**Masalah dan dampak:** dua fakta yang saling bertentangan dapat sama-sama aktif. Pada dua blanket replacement yang bersilangan, masing-masing operasi juga dapat menonaktifkan hasil operasi lain. Bila merge suatu edge gagal setelah node/edge sebelumnya sukses, graph tertinggal dalam keadaan batch parsial. Retry menambah importance lagi karena `+0.5` tidak dibatasi event ID.

**Dasar HIGH:** validasi single-valued hanya aman terhadap satu batch lokal; invariant graph tidak terlindungi terhadap kegagalan sebagian dan request bersamaan.

**Saran:** satu transaksi graph untuk validasi konflik, penulisan batch, dan supersession. Serialisasikan perubahan untuk `(scope, subject, relation)` melalui lock/version yang benar; sekadar membungkus query tanpa melindungi read-before-write belum cukup. Catat event yang telah diterapkan sehingga retry tidak menguatkan fakta dua kali.

**Validasi:** bukti statis dan semantik SDK. Tes penerimaan memerlukan Neo4j sementara: fault injection antarquery serta dua transaksi berlomba untuk satu relasi single-valued.

### H07 — Retry memakai waktu pemrosesan dan dapat mengaktifkan fakta lama

**Bukti:** [memory_service.py:607](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:607) tidak meneruskan waktu pesan kepada extractor, walaupun snapshot menyimpan `created_at`. [llm_service.py:1251](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1251) membangun clock aktual saat ekstraksi. [neo4j_service.py:349](D:/Nafiz/Career/Project/personal-assistant/backend/services/neo4j_service.py:349) mengaktifkan ulang edge existing ketika diterima; TTL dan `last_confirmed_at` diisi dari `timestamp()` pemrosesan.

**Pemicu:** pesan “besok aku menghadiri konferensi” diekstrak ulang beberapa hari setelah dibuat; atau job lama `WORKS_AT Acme` baru berhasil setelah koreksi `WORKS_AT Beta` telah diproses.

**Masalah dan dampak:** waktu relatif bergeser. Fakta/state lama tampak baru dikonfirmasi, TTL diperpanjang, dan edge yang pernah superseded dapat diaktifkan kembali. Pengurutan daftar retry berdasarkan `created_at` tidak menjamin urutan seluruh writer karena jalur chat dan retry berjalan terpisah. Tidak ada pemeriksaan bahwa event yang diterapkan lebih baru dari versi fakta.

**Dasar HIGH:** retry yang ditujukan untuk pemulihan dapat mengubah makna temporal dan membalik koreksi yang sudah benar.

**Saran:** simpan waktu penerimaan user secara eksplisit sebelum generation; bedakan `event_at`, `valid_from`, `processed_at`, dan `confirmed_at`. Gunakan event time untuk resolusi kata relatif dan TTL. Terapkan event secara berurutan atau dengan per-fact version check. Simpan kemunculan event berulang terpisah, bukan seluruh kunjungan/pembelian yang sama di-MERGE menjadi satu kejadian.

**Validasi:** `test_old_outbox_timestamp_not_used_for_extraction` menunjukkan job bertanggal 2020 menerima konteks waktu 2026. Jalur pengaktifan ulang graph dibuktikan statis; tidak ada klaim respons model hidup pada tanggal tersebut.

### H08 — Kontrak ekstraksi tidak dapat mencabut fakta tanpa pengganti sejenis

**Bukti:** [memory_policy.py:124](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_policy.py:124) hanya memiliki operasi edge positif dan atribut supersession, tanpa operasi retraction. [neo4j_service.py:426](D:/Nafiz/Career/Project/personal-assistant/backend/services/neo4j_service.py:426) mensyaratkan edge baru yang disetujui dan membatasi supersession pada **tipe relasi yang sama**. ID fakta baru sendiri dikeluarkan dari daftar supersedes pada baris 421–425.

**Pemicu:** “Aku sudah tidak bekerja di Acme” tanpa menyebut kantor pengganti, atau “Aku sudah tidak pacaran dengan X”.

**Masalah dan dampak:** output kosong tidak menonaktifkan fakta lama. Mengeluarkan `WORKS_AT Acme` lagi justru mengonfirmasinya. Mengeluarkan `WORKED_AT`/`NO_LONGER_WORKS_AT` dengan `supersedes` juga tidak mencabut `WORKS_AT`, karena query mencari tipe relasi yang baru. Membuat target fiktif untuk `WORKS_AT` merusak semantics. Jadi prompt yang meminta mengenali “sudah tidak” tidak didukung kontrak write yang memadai.

**Dasar HIGH:** user tidak dapat mengoreksi kelas fakta inti melalui bahasa percakapan tanpa mempertahankan fakta salah atau menciptakan fakta palsu.

**Saran:** kontrak operasi eksplisit `assert`, `retract`, `correct`; retraction mengacu fact ID dengan verifikasi subject, scope, dan bukti ucapan terbaru, tanpa memerlukan edge pengganti. Jika fakta lama tidak masuk retrieval, lakukan lookup khusus subject+relation, bukan menebak ID. Jangan membuka supersession sembarang relasi tanpa validasi.

**Validasi:** bukti schema dan Cypher. Tes penerimaan: assert kantor Acme, retract tanpa pengganti, lalu pastikan tidak ada `WORKS_AT Acme` current dan tidak ada kantor fiktif.

### H09 — Fakta usang tetap masuk prompt melalui memori vektor

**Bukti:** [qdrant_service.py:244](D:/Nafiz/Career/Project/personal-assistant/backend/services/qdrant_service.py:244) hanya menyaring role, epistemic status, dan scope; tidak mengecek supersession, expiry, atau koreksi. [memory_service.py:389](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:389) menggabungkan hasil graph dan vector tanpa rekonsiliasi. [llm_service.py:335](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:335) memasukkan keduanya ke prompt tanpa aturan khusus bahwa fakta current yang telah dikoreksi mengalahkan assertion lama.

**Pemicu:** graph sudah mengoreksi Acme menjadi Beta, tetapi vector ucapan “Aku kerja di Acme” mempunyai similarity tinggi. Hal serupa terjadi setelah edit/delete fact melalui editor graph.

**Masalah dan dampak:** perbaikan graph tidak cukup untuk memperbaiki jawaban AI. Vector lama tetap dilabeli assertion dan dapat bersaing dengan fakta current. Timestamp penyimpanan saja bukan status validitas. Bobot recency kecil juga tidak menjamin koreksi terbaru masuk tiga hasil akhir.

**Dasar HIGH:** jalur retrieval lain dapat membatalkan manfaat dari koreksi dan TTL graph pada pertanyaan keadaan sekarang.

**Saran:** tautkan assertion/event ke fact version dan status; propagasikan retraction/koreksi sebagai tombstone atau metadata; rekonsiliasi sebelum prompt. Untuk query current, prioritaskan fakta aktif dan sertakan assertion lama hanya sebagai riwayat yang jelas ditandai. Untuk query historical, tampilkan timeline perubahan.

**Validasi:** `test_current_read_does_not_reconcile_vector_with_graph` membuktikan “Acme” dan fakta current “Beta” diteruskan bersama ke prompt. Tidak diklaim model pasti memilih Acme; ketidakselarasan evidence-lah yang terkonfirmasi.

### H10 — Ringkasan kehilangan pembaruan dan pesan tanpa checkpoint

**Bukti:** [memory_service.py:836](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:836) memilih pesan yang akan dilipat dari count dan history snapshot. Chat di-commit pada baris 897; summary dibuat setelahnya dan ditulis langsung ke `conversation.summary` pada baris 910–916, tanpa version atau `summarized_through_message_id`.

**Pemicu A:** dua save memakai summary awal S0; ringkasan yang lebih lama selesai belakangan. **Pemicu B:** commit chat berhasil tetapi penyimpanan summary gagal atau proses berhenti di antaranya.

**Masalah dan dampak:** A menghasilkan lost update: S0+A menimpa S0+B. Pada B, turn berikutnya memakai window yang sudah maju dan melipat dua pesan berikutnya; dua pesan yang gagal dilipat tidak dicoba ulang. Data mentah masih ada di SQLite, tetapi hilang dari konteks AI sampai ada proses rekonstruksi yang tidak tersedia pada jalur normal.

**Dasar HIGH:** percakapan panjang kehilangan konteks diam-diam, bahkan ketika semua pesan mentah tetap tersimpan.

**Saran:** checkpoint dan versi summary; derive rentang dari sequence pesan, bukan panjang window saja. Persist summary job secara durable. Commit summary dan checkpoint secara atomik memakai compare-and-swap; apabila versi berubah, hitung ulang. Serialisasikan update per conversation dan sediakan rekonstruksi dari sumber mentah.

**Validasi:** `test_stale_summary_overwrites_newer_summary` menggunakan dua thread; `test_summary_failed_commit_loses_folded_messages` membuktikan `old-0`/`old-1` hilang dari summary dan giliran berikutnya langsung melipat `old-2`/`old-3`.

### H11 — Turn tidak mempunyai identitas durable untuk stop, retry, dan concurrency

**Bukti:** [chat_routes.py:373](D:/Nafiz/Career/Project/personal-assistant/backend/routes/chat_routes.py:373) dapat keluar ketika client disconnect; user/assistant baru dibuat setelah generation pada baris 393 dan [memory_service.py:824](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:824). Endpoint nonstream malah menjadwalkan commit setelah respons melalui BackgroundTasks pada [chat_routes.py:239](D:/Nafiz/Career/Project/personal-assistant/backend/routes/chat_routes.py:239). Schema request tidak mempunyai turn/idempotency key. Frontend mengulang pesan saat stream berakhir tanpa `done` pada [page.tsx:472](D:/Nafiz/Career/Project/personal-assistant/frontend/app/chat/page.tsx:472).

**Pemicu:** user menekan stop; jaringan putus setelah beberapa delta; atau server sudah commit tetapi terminal event tidak sampai. Dua tab juga dapat menyiapkan history yang sama sebelum salah satu turn disimpan.

**Masalah dan dampak:** turn yang terlihat di UI bisa tidak ada pada history backend. Sebaliknya, retry sesudah commit dapat menyimpan pesan dan memory event kedua kalinya karena UUID lokal bubble tidak dikirim ke backend. Turn paralel menjawab snapshot history lama tanpa mengetahui turn lain; urutan commit mengikuti completion, bukan urutan penerimaan user.

**Dasar HIGH:** state percakapan dan memori tidak konsisten pada gangguan jaringan biasa; efek dapat berupa kehilangan konteks maupun duplikasi permanen.

**Saran:** persist user turn dengan idempotency key dan sequence sebelum model dipanggil; status `generating/completed/interrupted/failed`; simpan partial response sebagai interrupted dan jangan ekstrak sebagai fakta assistant. Retry melanjutkan/membaca turn sama. Gunakan antrean atau optimistic concurrency per conversation. Final event hanya mengonfirmasi transaksi yang sudah dapat diambil ulang melalui turn ID.

**Validasi:** bukti statis lintas frontend/backend. Tes penerimaan: disconnect sebelum write, setelah commit sebelum `done`, dan dua request bersamaan untuk conversation yang sama.

### H12 — Context window dibatasi jumlah pesan, bukan anggaran token

**Bukti:** [chat_sch.py:5](D:/Nafiz/Career/Project/personal-assistant/backend/schemas/chat_sch.py:5) tidak membatasi panjang pesan. [memory_service.py:404](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:404) mengambil 30 pesan tanpa anggaran token. [llm_service.py:263](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:263) menyertakan seluruh teks vector dan [llm_service.py:356](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:356) menambahkan history utuh. Batas 2048 token hanya untuk output.

**Pemicu:** paste dokumen besar, beberapa respons panjang, tiga vector dari dokumen panjang, atau perpindahan ke model dengan context window lebih kecil.

**Masalah dan dampak:** prompt dapat melampaui kapasitas model sebelum percakapan mencapai ambang summary. Context yang sama dikirim lagi ke planner, final generation, dan provider fallback; ini menghasilkan penolakan API, latensi, dan biaya berulang. Batas ringkasan 3500 karakter tidak membatasi bagian prompt lain.

**Dasar HIGH:** fungsi chat dapat gagal berulang pada input sah dan session yang sama; pemangkasan berdasarkan jumlah pesan tidak menyelesaikannya.

**Saran:** anggaran token menurut model/provider untuk system, memory, history, tools, input, serta cadangan output. Chunk/retrieve dokumen panjang dan ringkas history sebelum batas terlampaui. Terapkan batas input terukur dengan respons yang dapat dipahami pengguna. Jangan mengirim prompt yang sama ke model fallback tanpa menyesuaikan budget.

**Validasi:** `test_prompt_has_no_input_budget` membuktikan pesan 600.000 karakter diterima schema dan masuk prompt utuh bersama history sebesar itu. Tidak dilakukan pengiriman payload besar ke provider.

## 3. MEDIUM

### M01 — Stream membuang spasi dan newline yang bermakna

**Bukti:** [llm_service.py:1043](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1043) hanya meneruskan delta bila `content and content.strip()` benar.

**Pemicu:** provider mengirim chunk terpisah berisi spasi, newline, atau indentation.

**Masalah/dampak dan severity:** `hello`, ` `, `world`, `\n`, `next` berubah menjadi `helloworldnext`. Markdown, tabel, dan kode dapat rusak; indentation Python mempunyai makna program. MEDIUM karena kerusakan bergantung pada pemisahan chunk provider, tetapi reproduksinya deterministik dan memengaruhi teks tersimpan maupun UI.

**Saran:** teruskan setiap delta string yang tidak kosong; gunakan `.strip()` hanya untuk menentukan apakah pernah ada teks terlihat bagi deteksi empty response. Jangan mengubah byte teks yang disusun kembali.

**Validasi:** `test_stream_discards_semantic_whitespace` menghasilkan tepat `helloworldnext` dari lima chunk tersebut.

### M02 — Regex pertanyaan melewatkan fakta eksplisit

**Bukti:** [llm_service.py:1101](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1101) mengenali assertion melalui daftar subjek/predikat terbatas. Baris 1122–1129 menganggap tanda tanya atau kata tanya cukup untuk recall-only; baris 1247 mengembalikan graph kosong tanpa memanggil extractor.

**Pemicu yang terkonfirmasi:** “Golongan darahku O, apa sudah tercatat?”, “Project Atlas memakai PostgreSQL, bagaimana optimasinya?”, dan “I work at Acme. Can you remember that?”

**Masalah/dampak dan severity:** fakta baru yang eksplisit hilang dari graph. Sistem tidak memberi error karena ini diperlakukan sebagai hasil kosong yang sah. MEDIUM karena subset frasa terkena, bukan seluruh extraction. Pola seperti “Aku alergi kacang, makanan apa yang aman?” justru terdeteksi oleh regex assertion; contoh itu tidak digunakan sebagai bukti kegagalan.

**Saran:** klasifikasi per klausa yang membedakan assertion, permintaan, dan pertanyaan; gunakan jalur skip hanya untuk input yang benar-benar pasti tanpa fakta. Sertakan multilingual dan fakta project dalam evaluasi. Jangan hanya menambah beberapa keyword lalu menganggap masalah selesai.

**Validasi:** ketiga contoh pada `test_real_assertions_are_discarded_by_question_regex` dilewati tanpa satu pun pemanggilan LLM ekstraksi.

### M03 — Semua ucapan user dilabeli sebagai assertion

**Bukti:** [memory_service.py:636](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:636) menyimpan pesan user utuh dengan `epistemic_status=user_assertion`; tidak memeriksa apakah extraction menghasilkan fakta. [qdrant_service.py:175](D:/Nafiz/Career/Project/personal-assistant/backend/services/qdrant_service.py:175) menegaskan label itu tanpa klasifikasi isi.

**Pemicu:** recall-only “Siapa pacarku?”, skenario fiktif, kutipan instruksi, dan jawaban eliptis seperti “iya” atau “dia di sana”.

**Masalah/dampak dan severity:** provenance *ditulis user* dicampur dengan status *user menyatakan fakta*. Pesan yang tidak mengandung assertion ikut antre retrieval faktual, menggeser evidence yang berguna, atau dipahami sebagai fakta dengan konteks yang tidak lengkap. Vector pesan eliptis tidak menyimpan dialog yang dibutuhkan untuk menafsirkan rujukannya. MEDIUM: salah klasifikasi dan hilangnya konteks terbukti; keberhasilan prompt injection atau halusinasi model tidak diklaim.

**Saran:** pisahkan arsip percakapan dan assertion terverifikasi. Simpan span assertion beserta source message, role, modality, polarity, dan rujukan yang sudah di-resolve. Pertahankan kutipan/hipotesis sebagai tipe berbeda; raw history boleh diretrieve untuk kontinuitas dengan label yang benar.

**Validasi:** `test_recall_question_is_stored_as_assertion` membuktikan “Siapa pacarku?” masuk jalur vector sebagai `user_assertion` walaupun graph extraction kosong.

### M04 — Satu embedding per pesan mengabaikan ekor pesan panjang

**Bukti:** [qdrant_service.py:142](D:/Nafiz/Career/Project/personal-assistant/backend/services/qdrant_service.py:142) memanggil `encode` sekali atas seluruh pesan. Baris 177 menyimpan seluruh teks pada payload, sementara baris 194 menghasilkan satu vector. Tidak ada chunking. Model default adalah multilingual-e5-large; [model card penulis](https://huggingface.co/intfloat/multilingual-e5-large#limitations) menjelaskan truncation input panjang ke 512 token.

**Pemicu:** fakta unik berada di bagian akhir pesan lebih panjang dari jendela embedding, misalnya keputusan arsitektur di akhir dokumen.

**Masalah/dampak dan severity:** payload tampak lengkap, tetapi similarity terutama mewakili bagian awal. Query tentang fakta akhir dapat gagal mengambil pesan tersebut. Bila bagian awal cocok, seluruh dokumen malah masuk prompt dan memperburuk H12. MEDIUM karena batas encoder menimbulkan blind spot tertentu, bukan kehilangan raw text.

**Saran:** chunk menurut tokenizer model dengan overlap; simpan message ID dan span offset; retrieve/rerank chunk relevan, lalu perluas tetangga seperlunya. Batasi panjang payload yang dikirim ke prompt.

**Validasi:** bukti kode dan dokumentasi primer. Tidak menjalankan inference embedding untuk mengukur recall aktual; uji penerimaan harus menempatkan fakta pembeda setelah token 512.

### M05 — Query graph berulang memindai kandidat luas dan memangkas konteks yang benar

**Bukti:** [neo4j_service.py:502](D:/Nafiz/Career/Project/personal-assistant/backend/services/neo4j_service.py:502) menjalankan query terpisah secara serial untuk tiap keyword. Query dimulai dari semua pola `(n:Entity)-[r]->(m:Entity)`, memakai regex pada nama dan transformasi tipe relasi, lalu sort dan `LIMIT 5`. Schema startup hanya membuat constraint identitas, bukan indeks pencarian yang sesuai. Penulisan graph juga memakai `session.run` per node, per edge, dan pemeriksaan tambahan.

**Pemicu:** graph membesar, keyword umum seperti `nafiz`, beberapa subject mempunyai `WORKS_AT`, atau extraction berisi puluhan node/edge.

**Masalah/dampak dan severity:** beban pencarian meningkat kira-kira mengikuti jumlah keyword dikali kandidat relasi yang harus diperiksa. `LIMIT` setelah sort tidak menghilangkan pekerjaan pencarian kandidat. Keyword subject dan relation diproses sendiri-sendiri; tidak ada syarat gabungan “WORKS_AT milik Nafiz”. Lima fakta orang lain yang berimportance tinggi dapat menghabiskan hasil relation, sementara lima fakta Nafiz lain menghabiskan hasil subject. Koreksi kemudian tidak memperoleh fact ID yang diperlukan.

**Saran:** resolve entity key dahulu, lakukan traversal terbatas dan predicate filtering; gunakan full-text index untuk pencarian nama, batch query dengan `UNWIND`, global reranking/diversity, serta budget hasil. Batch write dalam transaksi sesuai H06. Verifikasi dengan `EXPLAIN/PROFILE` dan dataset yang memuat banyak orang/relasi serupa.

**Validasi:** bukti statis; dampak latensi absolut belum diukur, sehingga tidak diklaim ada timeout produksi saat ini. MEDIUM karena sensitivitas terhadap ukuran dan komposisi graph.

### M06 — Output ekstraksi tanpa schema yang diminta dianggap sukses kosong

**Bukti:** [llm_service.py:1137](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1137) mengubah non-dict menjadi graph kosong; field `nodes`/`edges` yang hilang juga dianggap array kosong. [memory_policy.py:150](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_policy.py:150) menyediakan default kosong. [memory_service.py:615](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:615) lalu menetapkan `extraction_completed=True`.

**Pemicu:** provider mengembalikan JSON valid tetapi schema salah, misalnya `{"unexpected":"value"}` atau objek error yang tidak mempunyai nodes/edges.

**Masalah/dampak dan severity:** respons rusak disamakan dengan keputusan model yang sah bahwa tidak ada fakta. Job boleh selesai dan tidak diekstrak ulang. MEDIUM karena format response tertentu menghilangkan extraction secara diam-diam, sedangkan raw pesan masih tersedia.

**Saran:** validasi envelope asli lebih dahulu: dict dengan `nodes` dan `edges` wajib array. Pisahkan status `no_facts` dari `invalid_output`. Sanitasi field tambahan yang benar-benar tidak memengaruhi semantics hanya setelah envelope lolos. Invalid output harus dapat dicoba ulang secara terbatas dan teramati.

**Validasi:** `test_empty_extractor_object_is_accepted_as_success` menerima objek tanpa field graph sebagai sukses kosong bahkan dengan `raise_on_error=True`.

### M07 — Heuristik project memblokir pertanyaan publik dan web yang diperlukan

**Bukti:** [memory_service.py:161](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:161) menganggap keberadaan kata `project/proyek/projek` sebagai rujukan project dan dapat mengembalikan `ambiguous` meski daftar project kosong. [llm_service.py:320](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:320) mewajibkan klarifikasi dan melarang jawaban. [llm_service.py:467](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:467) mematikan web ketika ada satu hasil memori scoped, tanpa menilai apakah pertanyaan sebenarnya internal.

**Pemicu:** “Apa beda project management dan product management?” di chat umum; atau “Berapa harga Pertamax hari ini?” di project yang memiliki satu vector hit.

**Masalah/dampak dan severity:** pertanyaan konsep umum dipaksa menjadi klarifikasi project. Pertanyaan publik aktual dapat kehilangan tool web hanya karena retrieval menemukan kemiripan pada memori project. MEDIUM karena bergantung pada frasa dan konteks scope, tetapi keputusan tool dapat salah secara deterministik.

**Saran:** bedakan penyebutan konsep project dari rujukan ke project milik user. Ketersediaan tool berdasarkan intent informasi, bukan sekadar ada/tidaknya hit. Pertahankan pembatasan detail internal, tetapi jangan melarang verifikasi publik yang relevan.

**Validasi:** dua probe `test_project_keyword_blocks_generic_public_question` dan `test_project_recall_blocks_unrelated_public_fact_if_memory_hit_exists` mengonfirmasi kedua jalur.

### M08 — Semua entitas Project digabung ke project aktif

**Bukti:** [llm_service.py:1339](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1339) menganggap node Project pertama sebagai active project dan mengganti namanya. Lebih jauh, [neo4j_service.py:190](D:/Nafiz/Career/Project/personal-assistant/backend/services/neo4j_service.py:190) memetakan **setiap** node berlabel `Project` ke `project_entity_key` yang sama ketika active project tersedia.

**Pemicu:** di project Atlas, user menyatakan “Atlas bergantung pada project Boreal”. Extraction yang benar menghasilkan dua Project dan relasi `DEPENDS_ON`.

**Masalah/dampak dan severity:** kedua endpoint menjadi identitas yang sama, relasi menjadi self-loop, dan nama project aktif dapat ditimpa nama Project terakhir. Scope penyimpanan dicampur dengan identitas entitas yang sedang dibicarakan. MEDIUM karena kasus multi-project dalam satu extraction, tetapi korupsi struktur deterministik.

**Saran:** hanya node yang secara eksplisit terhubung ke ID active project memakai identitas tersebut. Entitas project eksternal mempunyai ID terpisah. Scope fakta tetap dapat Atlas walaupun fakta menyebut Boreal. Jangan mengganti node pertama hanya karena labelnya Project.

**Validasi:** `test_all_project_nodes_collapse_to_active_project` menjalankan merge dengan transport graph perekam dan membuktikan source=target serta penulisan nama `atlas`, lalu `boreal`, ke identitas yang sama.

### M09 — Parafrasa identitas memecah orang yang sama menjadi beberapa node

**Bukti:** [neo4j_service.py:136](D:/Nafiz/Career/Project/personal-assistant/backend/services/neo4j_service.py:136) membentuk hash dari `label|name|identity_context`; normalisasi hanya lowercase dan whitespace. Isi identity_context dihasilkan model. Tidak ada registry canonical entity/alias atau tahap lookup yang memverifikasi kandidat sebelum membuat ID baru.

**Pemicu:** Siska diperkenalkan sebagai “ibu nafiz”, lalu pada turn lain extractor menyebut “ibu dari nafiz”; perubahan deskripsi identitas juga dapat memicu hal yang sama.

**Masalah/dampak dan severity:** fakta satu orang tersebar pada beberapa node. Supersession yang membatasi source entity tidak dapat menjangkau node varian; pencarian nama dapat mengembalikan fakta yang tampak berkonflik. MEDIUM karena membutuhkan variasi identity_context; aturan ini tetap berguna untuk mencegah penggabungan orang berbeda dan tidak boleh sekadar dihapus.

**Saran:** canonical entity ID stabil, alias, dan atribut pembeda terstruktur; lakukan candidate matching lalu simpan keputusan entity linking. Jika ambigu, minta klarifikasi/karantina. Deskripsi bahasa alami menjadi atribut evidence, bukan satu-satunya primary identity.

**Validasi:** `test_identity_paraphrases_split_the_same_person` membuktikan dua deskripsi sinonim menghasilkan key berbeda. Frekuensi variasi model belum diukur.

### M10 — Satu kegagalan inisialisasi mematikan embedding sampai restart

**Bukti:** [qdrant_service.py:109](D:/Nafiz/Career/Project/personal-assistant/backend/services/qdrant_service.py:109) menolak percobaan berikutnya jika `_encoder_load_attempted` sudah true. Flag di-set sebelum load dan `_ensure_collection`, kemudian tidak direset ketika exception terjadi.

**Pemicu:** file model belum tersedia saat startup, error sementara saat membuka collection, atau keadaan Qdrant belum siap ketika warmup berlangsung.

**Masalah/dampak dan severity:** setelah penyebab eksternal dipulihkan, seluruh request tetap melempar `EmbeddingUnavailableError` tanpa mencoba load lagi. Strict streaming kemudian memperbesar efek sesuai H03. MEDIUM karena pemicu inisialisasi tertentu dan restart dapat memulihkan.

**Saran:** state inisialisasi dengan backoff dan retry terbatas; bedakan error model permanen dari error store sementara; sediakan reset/warmup terkontrol. Gunakan lock untuk memastikan hanya satu percobaan load berjalan, tanpa menjadikan kegagalan pertama permanen.

**Validasi:** `test_embedding_failure_is_permanently_latched` memanggil load dua kali setelah kegagalan sintetis; constructor hanya dipanggil sekali.

### M11 — Reindex menganggap jumlah vektor sebagai bukti kelengkapan

**Bukti:** [memory_service.py:1086](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:1086) melewati reindex ketika `vectors >= len(snapshots)`. Tidak dibandingkan ID point, fingerprint isi, scope, atau versi embedding terhadap outbox.

**Pemicu:** collection berisi orphan/point lama yang menggantikan jumlah point yang hilang. Contoh: outbox A,B; collection A,X. Jumlah sama, tetapi B belum diindeks.

**Masalah/dampak dan severity:** mekanisme recovery menyatakan tidak perlu bekerja walaupun projection tidak lengkap. Ketika full reindex dipicu, seluruh job dimuat dengan `.all()` dan seluruh pesan di-embed satu per satu, termasuk yang sebenarnya tidak berubah. MEDIUM karena kasus drift/migrasi, tetapi recovery yang salah dapat mempertahankan blind spot lintas restart.

**Saran:** rekonsiliasi berdasarkan event ID dan versi/fingerprint, bukan cardinality. Simpan checkpoint migrasi yang durable; scan/batch bertahap; hormati tombstone H05. Validasi versi encoder juga diperlukan ketika mengganti model dengan dimensi yang sama—kesamaan dimensi tidak menjamin ruang embedding sama.

**Validasi:** `test_reindex_count_match_can_hide_missing_point` membuktikan count yang cocok menyebabkan skip tanpa satu pun upsert. Contoh A,B versus A,X adalah penjelasan konsekuensi guard tersebut, bukan inspeksi collection produksi.

### M12 — Dua read_url identik dalam satu batch menyebabkan StopIteration

**Bukti:** [llm_service.py:865](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:865) mencari hasil URL di `pages` jika URL ada di `already_read`; baris 871 sudah menambahkan URL pertama ke set itu ketika request baru dijadwalkan, sebelum hasilnya ada di `pages`.

**Pemicu:** model mengeluarkan dua tool call `read_url` dengan URL sama dalam satu respons planning.

**Masalah/dampak dan severity:** call kedua menjalankan `next(...)` atas daftar yang belum mempunyai halaman tersebut. `StopIteration` diubah menjadi `InternalFeatureError`; turn gagal padahal kedua call valid dan cukup dideduplikasi. MEDIUM karena batch tertentu, bukan seluruh tool loop.

**Saran:** pisahkan URL pending dan completed. Kelompokkan call ID per URL; satu fetch memasok hasil ke semua call ID. Duplicate bukan error terminal. Jangan menandai selesai sebelum hasil tersedia.

**Validasi:** `test_duplicate_read_url_in_one_batch_raises` membuktikan `StopIteration` tercatat di error diagnostik.

### M13 — Satu sumber web gagal menggagalkan hasil lain yang berhasil

**Bukti:** [web_search_service.py:305](D:/Nafiz/Career/Project/personal-assistant/backend/services/web_search_service.py:305) melempar exception ketika ada satu query gagal pada strict mode, walaupun `result_groups` berisi hasil sukses. Tool loop selalu memakai mode itu pada [llm_service.py:828](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:828). Untuk pembacaan dua halaman, baris 900–915 menggagalkan turn jika salah satunya gagal.

**Pemicu:** tiga pencarian paralel menghasilkan dua hasil valid dan satu timeout; atau dua URL dipilih dan satu menolak akses.

**Masalah/dampak dan severity:** hasil yang dapat dipakai dibuang dan user menerima diagnosis internal. Tool juga tidak dapat memberi model kesempatan memilih URL alternatif atau menjawab sebatas bukti yang sudah ada. MEDIUM karena kegagalan sumber eksternal parsial adalah kondisi lazim yang semestinya dapat dipulihkan, tetapi dampaknya terbatas pada turn riset itu.

**Saran:** tool result per call berisi success/error; pertahankan evidence sukses; tandai pencarian parsial dan biarkan model menjawab batas bukti atau memakai sisa budget untuk pengganti. Kesalahan argumen tool yang dapat diperbaiki sebaiknya dikembalikan ke model, bukan langsung mematikan percakapan.

**Validasi:** `test_partial_search_failure_raises_in_production_mode` membuktikan satu hasil sukses plus satu failure berakhir exception. Jalur read parsial ditelusuri statis.

### M14 — Filter TF-IDF membuang bukti relevan lintas bahasa

**Bukti:** [web_search_service.py:162](D:/Nafiz/Career/Project/personal-assistant/backend/services/web_search_service.py:162) hanya mempertahankan similarity leksikal di atas nol. Filter dilakukan terhadap query pada baris 283–286 dan sekali lagi terhadap `research_goal` pada baris 316–319.

**Pemicu:** model menulis query teknis Inggris, sementara research_goal dalam Bahasa Indonesia; atau sumber relevan memakai sinonim yang tidak overlap.

**Masalah/dampak dan severity:** hasil yang semantik relevan dari search engine bisa berubah menjadi `no_results`. Kesamaan kata bukan syarat perlu untuk relevansi, terutama pada asisten multilingual. MEDIUM karena kombinasi bahasa/kosakata, bukan semua pencarian.

**Saran:** gunakan TF-IDF sebagai sinyal reranking lunak; jangan hapus semua kandidat hanya karena overlap nol. Pertahankan kuota kandidat per query dan gunakan semantic/cross-encoder reranker bila diperlukan. Evaluasi silang bahasa dan kueri perbandingan.

**Validasi:** `test_tfidf_discards_translation_of_research_goal` menunjukkan sumber “How to reduce database latency” dibuang oleh goal “cara mempercepat basis data”.

### M15 — Chat sederhana memanggil model dua kali sebelum selesai

**Bukti:** [llm_service.py:779](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:779) selalu menjalankan planning nonstream ketika tool diizinkan. Jika tidak ada tool call, teks planner dibuang dan loop berhenti pada baris 796. Final stream tetap dibuat pada baris 1021.

**Pemicu:** sapaan/percakapan sederhana di luar pembatasan project.

**Masalah/dampak dan severity:** model dapat sudah menghasilkan jawaban sampai budget 500 token, tetapi aplikasi mengulang generation dengan prompt sama. Selain itu, router memori dan extraction/title dapat menambah panggilan internal. Time-to-first-visible-token menunggu roundtrip planning yang tidak memberi manfaat pada kasus ini. MEDIUM karena biaya dan latency sistematis, bukan kegagalan kebenaran langsung.

**Saran:** gunakan satu request streaming dengan tool call accumulation, atau planner yang benar-benar hanya memutuskan tool dengan budget kecil. Fast path untuk input yang jelas tidak membutuhkan retrieval dapat membantu, tetapi harus diuji agar tidak meniadakan verifikasi fakta. Pertahankan dukungan metadata provider saat menyatukan alur.

**Validasi:** `test_simple_chat_has_two_generation_calls` membuktikan dua pemanggilan model dan teks planner pertama tidak digunakan kembali. Tidak ada klaim berapa milidetik atau rupiah penghematannya sebelum benchmark.

### M16 — Timestamp sama dapat membalik urutan user dan assistant

**Bukti:** [memory_service.py:417](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:417) mengurutkan hanya `created_at DESC`, lalu membalik hasil. Model Message pada [message.py:20](D:/Nafiz/Career/Project/personal-assistant/backend/models/message.py:20) tidak memiliki sequence turn atau tie-breaker yang mempertahankan role ordering. Pasangan pesan ditambahkan dalam flush yang sama.

**Pemicu:** dua atau lebih row berbagi timestamp, misalnya resolusi clock atau penyimpanan batch yang menghasilkan nilai sama.

**Masalah/dampak dan severity:** SQL tidak menjamin urutan antarbaris yang nilainya sama. Pada SQLite terisolasi, insert user lalu assistant dengan timestamp identik menghasilkan history assistant lalu user setelah pembalikan. Ini mengubah konteks model dan pilihan pesan yang masuk summary. MEDIUM karena tie tertentu; tidak diklaim semua turn selalu terbalik.

**Saran:** gunakan sequence monotonik per conversation dan urutan role dalam turn; simpan turn ID. Urutkan pengambilan history dan compaction dengan sequence itu. UUID acak bukan penanda urutan percakapan.

**Validasi:** `test_same_timestamp_messages_reverse_role_order` mereproduksi pembalikan role dengan SQLite nyata sementara.

### M17 — Query memori tidak menerima konteks untuk meresolusikan rujukan

**Bukti:** [memory_service.py:277](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:277) mengirim hanya pesan terbaru ke `route_memory_query`; vector search pada baris 325 memakai string yang sama. History hanya dipakai resolver project, bukan contextual query rewriting untuk orang/objek umum. [llm_service.py:1399](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1399) juga tidak menerima history atau summary.

**Pemicu:** turn sebelumnya menyebut Budi, lalu user bertanya “dia kerja di mana sekarang?”. Fakta tempat kerja Budi ada di graph lama, tetapi tidak ada dalam 30 pesan terakhir.

**Masalah/dampak dan severity:** router tidak mempunyai informasi untuk mengubah `dia` menjadi Budi. Model jawaban memang menerima history, tetapi sudah terlambat untuk memperbaiki pencarian personal: tool yang tersedia hanya web. Embedding dari pertanyaan tanpa subjek juga lebih mudah mengambil orang atau percakapan lain. MEDIUM karena pertanyaan eliptis; frekuensi salah routing model belum diukur.

**Saran:** bangun query mandiri dari turn terbaru plus history/summary yang dibatasi, dengan identitas rujukan dan tingkat kepastian. Jika ambigu, klarifikasi. Gunakan hasil resolusi yang sama pada vector dan graph; jangan membiarkan rewriting mengubah kebutuhan informasi terbaru.

**Validasi:** bukti kontrak fungsi dan call site. Tes penerimaan memakai dua orang dengan profesi berbeda dan pertanyaan pronominal yang sama dalam dua konteks; retrieval harus berubah sesuai antecedent.

### M18 — Jawaban terpotong batas token tetap dinyatakan selesai

**Bukti:** [llm_service.py:1025](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1025) membatasi completion menjadi 2048 token. `_record_stream_diagnostics` menyimpan finish reason, tetapi [llm_service.py:1055](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:1055) hanya memutuskan recovery berdasarkan ada/tidaknya teks. [chat_routes.py:388](D:/Nafiz/Career/Project/personal-assistant/backend/routes/chat_routes.py:388) juga hanya memeriksa string kosong sebelum menyimpan dan mengirim `done`.

**Pemicu:** model berhenti dengan `finish_reason=length` setelah mengirim sebagian jawaban, misalnya analisis panjang atau kode lebih dari budget output.

**Masalah/dampak dan severity:** jawaban yang belum lengkap disimpan dan ditandai complete. Potongan kode yang belum menutup blok atau penjelasan yang kehilangan batasan terakhir tampil seperti hasil normal. MEDIUM karena bergantung panjang output dan semantik finish reason provider.

**Saran:** propagasikan finish reason ke orchestrator; tandai `incomplete` bila mencapai batas panjang. Sediakan continuation yang dibatasi atau budget output adaptif menurut jenis tugas dan context window. Jangan mengulang seluruh generation hanya karena terpotong, dan jangan menyatakan `done` lengkap ketika provider menyatakan sebaliknya.

**Validasi:** bukti statis. Tes penerimaan: mock stream berisi teks dan finish reason `length`; pastikan hasil tidak ditandai complete tanpa continuation atau status incomplete yang terlihat.

## 4. LOW

### L01 — Pelaporan token melewatkan pemanggilan AI internal dan turn gagal

**Bukti:** [llm_service.py:228](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py:228) mengembalikan completion untuk router/extractor/title/summary tanpa pencatatan usage tersendiri. [memory_service.py:861](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py:861) hanya mencatat usage yang diserahkan jalur chat sukses; biaya diisi `0.0`. Jalur diagnosis error juga tidak mengembalikan usage untuk dicatat.

**Pemicu:** setiap percakapan yang menjalankan AI internal, termasuk retry extraction dan diagnosis kegagalan.

**Masalah/dampak dan severity:** statistik lokal bukan total konsumsi AI sebenarnya. Planner dan final pada stream normal memang diakumulasi; masalahnya adalah panggilan lain dan turn yang tidak sampai persistence sukses. LOW karena terutama memengaruhi observabilitas dan perencanaan biaya, bukan langsung mengubah fakta.

**Saran:** logging usage di wrapper setiap panggilan dengan `purpose`, provider/model, turn/job/attempt ID, latency, status, dan token. Bedakan biaya belum dihitung dari biaya nol. Jangan merekam ulang usage provider yang sama ketika mencoba ulang hanya proses penyimpanan.

**Validasi:** bukti statis. Tes penerimaan: satu chat, satu router, satu extraction retry, satu summary, dan satu diagnosis menghasilkan lima/lebih record panggilan yang dapat direkonsiliasi ke provider, sesuai jumlah attempt nyata.

## 5. Pengujian dan prioritas perbaikan

### 5.1 Hasil eksekusi

Harness: [ai_audit_2026_09_12_checks.py](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_audit_2026_09_12_checks.py).

Snapshot SHA-256 untuk 11 file aplikasi yang dirujuk: [ai_audit_2026_09_12_source_sha256.json](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_audit_2026_09_12_source_sha256.json). Gunakan snapshot ini untuk mengetahui apakah kode sudah berubah sejak bukti dan nomor baris diperiksa.

| Pemeriksaan | Hasil | Batas interpretasi |
|---|---|---|
| Suite bawaan `backend/tests/test_*.py` | 66/66 lulus; 0,351 detik waktu test runner | Dependensi layanan diganti mock; SQLite pengujian sementara; bukan integrasi produksi |
| Probe audit tambahan | 23/23 lulus; 0,337 detik waktu test runner | Assertion sengaja mengonfirmasi defect saat ini; bukan sertifikat kebenaran |
| Import/runtime harness | Berhasil dengan Python virtualenv proyek setelah eksekusi di luar sandbox disetujui | Waktu import sekitar beberapa detik tidak termasuk angka test runner |
| Neo4j native concurrency / query plan | Tidak dijalankan | Temuan Cypher diberi label bukti statis; tidak ada angka throughput/latency yang diklaim |
| LLM dan embedding hidup | Tidak dipanggil | Tidak ada pengukuran probabilitas halusinasi, efektivitas injection, atau recall embedding |

Versi dependensi yang terpasang saat pengujian: OpenAI SDK **3.6.0**, Neo4j driver **6.3.0**, Qdrant client **1.19.0**, SQLAlchemy **2.0.52**, sentence-transformers **6.0.1**, FastAPI **0.141.1**. Ini hasil pembacaan paket lokal, bukan rekomendasi versi terbaru.

Penjalanan awal harness diperbaiki karena pemblokiran seluruh `socket.connect` juga menghalangi socketpair internal asyncio Windows. Data sintetis summary kemudian diberi timestamp berbeda agar tes checkpoint tidak tercampur dengan M16. Contoh assertion yang ternyata dikenali regex dibuang dari kasus kegagalan dan dicatat pada M02. Kegagalan persiapan ini tidak dihitung sebagai defect aplikasi. Hasil tabel adalah penjalanan final setelah koreksi harness.

Untuk reproduksi dari PowerShell:

```powershell
Set-Location 'D:\Nafiz\Career\Project\personal-assistant\backend'
& 'D:\Nafiz\Career\Project\personal-assistant\backend\venv\Scripts\python.exe' 'D:\Nafiz\Career\Project\personal-assistant\backend\Analysis\ai_audit_2026_09_12_checks.py'
& 'D:\Nafiz\Career\Project\personal-assistant\backend\venv\Scripts\python.exe' 'D:\Nafiz\Career\Project\personal-assistant\backend\Analysis\ai_audit_2026_09_12_checks.py' --existing
```

Harness mengarahkan konfigurasi database ke direktori sementara, memasang Neo4j mock sebelum mengimpor services, memakai kredensial placeholder, dan memblokir resolusi alamat jaringan. SQLite temporer dibersihkan setelah selesai. **Probe yang lulus sekarang seharusnya diubah assertion-nya menjadi invariant yang benar ketika perbaikan diimplementasikan.** Jangan memasukkannya begitu saja ke CI sebagai tes yang mengharuskan bug tetap ada.

### 5.2 Pemetaan probe ke temuan

| Probe | Temuan yang didukung |
|---|---|
| `test_sync_client_ignores_configured_llm_timeout` | H02 |
| `test_processing_job_can_be_claimed_again` | H04 |
| `test_vector_write_can_finish_after_session_deletion` | H05 |
| `test_old_outbox_timestamp_not_used_for_extraction` | H07 |
| `test_current_read_does_not_reconcile_vector_with_graph` | H09 |
| `test_stale_summary_overwrites_newer_summary` | H10 |
| `test_summary_failed_commit_loses_folded_messages` | H10 |
| `test_prompt_has_no_input_budget` | H12 |
| `test_stream_discards_semantic_whitespace` | M01 |
| `test_real_assertions_are_discarded_by_question_regex` | M02 |
| `test_recall_question_is_stored_as_assertion` | M03 |
| `test_empty_extractor_object_is_accepted_as_success` | M06 |
| `test_project_keyword_blocks_generic_public_question` | M07 |
| `test_project_recall_blocks_unrelated_public_fact_if_memory_hit_exists` | M07 |
| `test_all_project_nodes_collapse_to_active_project` | M08 |
| `test_identity_paraphrases_split_the_same_person` | M09 |
| `test_embedding_failure_is_permanently_latched` | M10 |
| `test_reindex_count_match_can_hide_missing_point` | M11 |
| `test_duplicate_read_url_in_one_batch_raises` | M12 |
| `test_partial_search_failure_raises_in_production_mode` | M13 |
| `test_tfidf_discards_translation_of_research_goal` | M14 |
| `test_simple_chat_has_two_generation_calls` | M15 |
| `test_same_timestamp_messages_reverse_role_order` | M16 |

### 5.3 Urutan perbaikan yang disarankan

| Tahap | Temuan | Hasil yang harus dapat dibuktikan |
|---|---|---|
| 1 — Batasi dampak gangguan | H01–H03, M01, M12–M13, M18 | Worker lambat tidak membekukan chat; jawaban sukses tidak hilang karena kegagalan memory/web; stream merekonstruksi teks persis dan menyatakan status lengkap dengan benar |
| 2 — Tegakkan integritas write | H04–H08, H11, M08, M16 | Satu turn/event punya identitas dan urutan; replay tidak menggandakan efek; penghapusan bertahan terhadap worker terlambat; koreksi/retraction atomik dan berdasarkan event time |
| 3 — Pulihkan kontinuitas dan grounding | H09–H10, H12, M02–M04, M06–M07, M09, M17 | Bukti current selaras antarstore; ringkasan tidak melewatkan pesan; referen jelas; input sesuai anggaran model |
| 4 — Skalabilitas dan operasional | M05, M10–M11, M14–M15, L01 | Retrieval terukur pada dataset besar; recovery berdasarkan ID/versi; biaya seluruh panggilan dapat direkonsiliasi |

### 5.4 Celah pengujian yang perlu ditutup

Suite saat ini kuat dalam memeriksa bentuk prompt, keberadaan klausa filter, batas field, dan alur sukses sintetis. Sejumlah tes graph hanya mencari substring dalam query; keberadaan `is_current`, provenance, atau `NOT EXISTS` bukan bukti invariant tetap benar saat transaksi berjalan bersamaan. Tes partial-failure yang lulus menggunakan mode berbeda dari strict mode jalur chat, sehingga hasilnya tidak membuktikan degradasi yang sama pada penggunaan nyata.

Tambahkan integration test pada **database disposable** untuk transaksi graph, race delete, job lease, dan replay. Gunakan fault injection setelah tiap batas commit, bukan hanya exception sebelum seluruh fungsi. Tambahkan evaluasi retrieval/answer dengan kasus negasi, dua orang bernama sama, perubahan fakta, rujukan pronominal, lintas bahasa, dan pesan panjang. Untuk model hidup, ukur assertion precision/recall, ketepatan koreksi, faithfulness terhadap sumber, serta p50/p95 time-to-first-token dan completion time dengan jumlah panggilan per turn.

### 5.5 Perlindungan yang sudah ada dan tidak dilaporkan ulang sebagai bug

- Vector menolak role assistant; masalah lama berupa penyimpanan gabungan user+assistant tidak diperlakukan sebagai temuan aktif.
- Input schema graph memeriksa endpoint, nama relasi, confidence, dan konflik single-valued dalam satu extraction.
- Ada TTL untuk relasi sementara, filter current/expiry/review di graph, serta guard subject/relasi/scope untuk supersession. Temuan audit menyasar celah lintas transaksi, waktu event, dan lintas store.
- Context JSON meng-escape delimiter. Karena itu, audit tidak mengklaim serangan penutupan delimiter sudah berhasil. Pemisahan data/instruksi tetap bukan pembuktian ketahanan terhadap seluruh prompt injection.
- Tool web mempunyai allowlist URL dari pencarian, batas round, batas jumlah halaman, dan batas panjang konten. Audit tidak mengklaim SSRF lokal hanya dari tidak adanya resolusi DNS pada validator, karena pembacaan aktual dilakukan melalui layanan Jina eksternal.
- Tidak ada bukti dari audit ini bahwa seluruh graph sudah korup, semua jawaban halusinasi, atau seluruh memori hilang di mesin pengguna.

