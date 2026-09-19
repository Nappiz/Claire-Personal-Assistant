# Perbaikan komponen AI — M17, M18, dan L01

Tanggal: **13 September 2026**. Acuan: detail M17, M18, dan L01 dalam [audit asli](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_components_extreme_audit_2026-09-12.md). Ruang lingkup perbaikan mengikuti tiga temuan tersebut dan mempertahankan regresi perbaikan sebelumnya.

## 1. Status perbaikan

| ID | Severity audit | Masalah | Perbaikan dan bukti penerimaan |
|---|---|---|---|
| M17 | MEDIUM | Query memori tidak menerima konteks untuk meresolusikan rujukan | Router menerima history/summary terbatas; pemetaan rujukan divalidasi terhadap konteks. Vector dan graph memakai hasil resolusi yang sama. Pertanyaan identik tentang “dia” berubah menjadi Budi atau Andi sesuai history; ambiguity menghasilkan klarifikasi tanpa pencarian luas. |
| M18 | MEDIUM | Jawaban terpotong batas token tetap dinyatakan selesai | Finish reason dipropagasikan ke status jawaban, persistence, endpoint chat, SSE, cached replay, history, dan UI. Stream maupun jawaban planner dengan `length` mempertahankan teks dan ditandai `incomplete`, tanpa generation ulang seluruh jawaban. |
| L01 | LOW | Pelaporan token melewatkan pemanggilan AI internal dan turn gagal | Ledger `ai_invocations` mencatat setiap percobaan request provider secara terpisah dari commit chat. Router, extraction, title, summary, diagnosis, planner, jawaban, recovery, retry, failure, dan cancellation tercakup. Persistence retry tidak menghitung ulang request yang sama. |

## 2. Detail M17 — Resolusi rujukan sebelum retrieval

`retrieve_context` sekarang menerima `session_summary` selain `session_history`; kedua endpoint chat mengirimkannya. Request router yang sudah tersedia menerima konteks sebagai JSON pasif, maksimal 12 pesan terbaru, 1.500 karakter per pesan, 6.000 karakter history, serta 3.000 karakter summary. Perbaikan ini tidak menambahkan satu request LLM khusus rewriting.

Router mengembalikan status resolusi, confidence, kandidat, dan pasangan mention/entity. Resolusi diterima hanya jika confidence minimal 0,85, entitas benar-benar terdapat dalam konteks yang dikirim, mapping tidak bertentangan, dan semua rujukan yang didukung mendapat mapping. Query dibangun dengan mengganti span rujukan pada pertanyaan asli. Rewriting bebas dari model diabaikan, sehingga kebutuhan informasi, negasi, dan acuan waktu terbaru tetap dipertahankan.

Query hasil resolusi dipakai pada vector search; entitas yang sama diprioritaskan dalam keyword graph. Keyword tambahan harus muncul pada query atau merupakan relasi yang dikenal. Metadata resolusi juga masuk prompt jawaban dalam batas anggaran input yang sudah tersedia.

Jika antecedent tidak jelas, confidence rendah, mapping tidak valid, atau router gagal pada pertanyaan pronominal, jalur jawaban mengirim klarifikasi. Vector/graph tidak dicari memakai subjek yang belum jelas dan generation jawaban tambahan tidak dipanggil. Context invocation ikut disalin ke executor retrieval agar ledger tetap terkait turn asal.

**Batasan:** ini resolver konservatif untuk pola rujukan yang didukung, bukan jaminan seluruh bentuk elipsis bahasa alami dapat diselesaikan. Confidence berasal dari model dan tidak dianggap probabilitas yang terkalibrasi. Antecedent di luar history/summary terbatas bisa tidak tersedia; hasilnya perlu klarifikasi. Kecocokan nama dalam konteks membuktikan keberadaan antecedent, bukan kebenaran fakta tentang orang tersebut.

## 3. Detail M18 — Status jawaban terpotong

Event internal `completion` membawa `response_status` dan `finish_reason`. `length`, `max_tokens`, `max_output_tokens`, dan `content_filter` menghasilkan `incomplete`. Finish reason final tetap tersedia untuk membedakan penyebabnya.

Pesan assistant memiliki dua field durable baru. Status disimpan bersama teks, dikembalikan oleh endpoint nonstream dan SSE `done`, serta dipertahankan oleh retry dengan turn ID yang sama dan endpoint history. `done` menyatakan stream telah berakhir; field `response_status` menyatakan kelengkapan jawaban. Turn tetap diakhiri agar lease dilepas dan pesan berikutnya dapat diproses.

UI menampilkan “Jawaban ini belum lengkap. Kamu bisa meminta lanjutannya.” ketika menerima status tersebut, termasuk setelah history dimuat ulang. Jawaban parsial planner juga digunakan tanpa generation kedua. Penutupan generator stream menutup nested stream sehingga cancellation tercatat dan resource provider ditutup.

**Batasan:** tidak ada continuation otomatis; pengguna dapat meminta kelanjutan melalui turn berikutnya dengan jawaban parsial tetap berada di history. Metadata finish reason lama yang tidak pernah disimpan tidak dapat direkonstruksi. Default kompatibilitas untuk row historis adalah `complete`, bukan bukti bahwa semua jawaban historis memang lengkap. Jika provider tidak mengirim finish reason, pemotongan tidak dapat dideteksi hanya dari teks.

## 4. Detail L01 — Ledger usage per request provider

Wrapper sinkron/asinkron membuat UUID invocation dan record `started` sebelum memanggil provider. Record yang sama diperbarui setelah selesai. Field mencakup purpose, provider/model, conversation/turn/job ID bila tersedia, attempt request, attempt job, waktu dan latensi, status, request ID, response ID, finish reason, jenis error, serta usage asli dan token yang valid.

Retry tersembunyi SDK dinonaktifkan pada request yang diinstrumentasi. Retry transient yang dikonfigurasi dilakukan secara eksplisit dan dibatasi, sehingga setiap percobaan HTTP menghasilkan record sendiri. Fallback provider menghasilkan record tersendiri untuk masing-masing provider/model. Stream menyimpan snapshot usage terakhir; snapshot kumulatif tidak dijumlahkan berulang. Failure/cancellation tetap dicatat meskipun jawaban tidak sampai commit chat.

`invocation_ids` mengikuti agregat usage chat. Penyimpanan chat tidak membuat `LLMUsageLog` tambahan ketika request tersebut sudah tercatat di ledger. Jalur kompatibilitas tanpa invocation ID tetap mendukung log lama. Statistik token menjumlahkan ledger baru dan log historis, serta menambahkan jumlah invocation dan jumlah invocation dengan total token yang belum diketahui.

Usage hilang atau token tidak valid disimpan sebagai `NULL`, bukan nol buatan. Total dapat dihitung jika prompt dan completion token sama-sama tersedia. `total_cost` tetap `NULL` karena kalkulasi harga belum diterapkan. Ledger tidak memiliki foreign key ke chat agar penghapusan percakapan tidak menghapus rekam konsumsi; ledger tidak menyimpan isi prompt/jawaban.

Kegagalan database telemetry, termasuk rollback/cleanup, menghasilkan fallback log terstruktur dengan invocation ID yang sama dan tidak menggagalkan jawaban sukses. Metadata usage provider yang tidak kompatibel juga tidak menghapus jawaban.

**Batasan:** total lokal hanya menjumlahkan usage yang tersedia. Provider dapat menagih request yang gagal tanpa mengirim usage; nilainya tetap tidak diketahui. Panggilan internal historis yang tidak tercatat tidak dapat dipulihkan. Jika proses mati, record `started` dapat tertinggal tanpa hasil akhir. Saat ledger database tidak tersedia, fallback log memerlukan rekonsiliasi operasional; tidak ada replay otomatis atau jurnal durable kedua. Pengujian tidak membuktikan kesamaan dengan invoice provider nyata.

## 5. Pengujian

| Pemeriksaan | Hasil |
|---|---|
| Seluruh unittest backend | **143 lulus**, termasuk **26 tes baru** dalam suite M17/M18/L01 |
| Migrasi SQLite sementara | Upgrade seluruh chain ke head → downgrade ke revision sebelumnya → upgrade ke head berhasil; field/table cocok dengan model |
| Frontend TypeScript | `tsc --noEmit` lulus |
| Lint frontend yang berubah | `eslint app/chat/page.tsx app/chat/ChatBubble.tsx lib/sse.ts` lulus |

Tes baru mencakup dua orang dengan profesi berbeda, antecedent dari summary, ambiguity, entitas rekaan/confidence rendah, pelestarian negasi/waktu, pembatasan konteks, literal kata “dia”, dan acronym IT. Jalur truncation diuji pada stream, planner, endpoint nonstream, persistence, cached retry, SSE, dan history.

Ledger diuji menggunakan SQLite sementara dan SDK provider yang benar-benar diinstal, dengan HTTP `MockTransport`: respons 503 lalu sukses, stream SSE `length`, request/response ID, usage kumulatif, failure setelah usage, cancellation, pemanggilan internal, context executor, idempotensi finalization, persistence retry, usage tidak tersedia, metadata usage malformed, serta outage database telemetry. Tidak ada request AI berbayar dalam pengujian ini.

Perintah dari direktori backend:

```powershell
& '.\venv\Scripts\python.exe' -m unittest discover -s tests -q
```

Pengujian: [test_extreme_medium_17_18_low_ai_fixes.py](D:/Nafiz/Career/Project/personal-assistant/backend/tests/test_extreme_medium_17_18_low_ai_fixes.py). Log warning pada skenario fault injection merupakan kondisi yang sengaja diuji. Tidak dilakukan benchmark latensi produksi atau evaluasi resolver dengan model hidup.

## 6. Schema dan pengoperasian

Migration baru: [c7e9a210d643_ai_invocations_and_response_status.py](D:/Nafiz/Career/Project/personal-assistant/backend/alembic/versions/c7e9a210d643_ai_invocations_and_response_status.py), parent `a9c2f604d812`. Migration menambah field pesan, table ledger, dan index pencarian invocation.

Untuk database yang dikelola Alembic, jalankan upgrade ke head sebelum menjalankan versi backend ini. Untuk database SQLite lokal yang dibuat melalui startup tanpa tracking Alembic, restart menjalankan mekanisme kompatibilitas schema yang sudah tersedia dan membuat table baru. Jangan menjalankan chain Alembic secara buta pada database lokal yang schema-nya dibuat di luar tracking.

Pengujian migrasi dilakukan pada database disposable; database pengguna tidak dimigrasikan melalui pengujian ini. Restart backend untuk memuat kode dan schema baru. Frontend perlu menjalankan versi yang sudah diperbarui untuk menampilkan label `incomplete`.

File utama: [ai_usage_service.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/ai_usage_service.py), [ai_invocation.py](D:/Nafiz/Career/Project/personal-assistant/backend/models/ai_invocation.py), [llm_service.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py), [memory_service.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py), [chat_routes.py](D:/Nafiz/Career/Project/personal-assistant/backend/routes/chat_routes.py), [chat_sch.py](D:/Nafiz/Career/Project/personal-assistant/backend/schemas/chat_sch.py), [message.py](D:/Nafiz/Career/Project/personal-assistant/backend/models/message.py), [main.py](D:/Nafiz/Career/Project/personal-assistant/backend/main.py), [page.tsx](D:/Nafiz/Career/Project/personal-assistant/frontend/app/chat/page.tsx), [ChatBubble.tsx](D:/Nafiz/Career/Project/personal-assistant/frontend/app/chat/ChatBubble.tsx), dan [sse.ts](D:/Nafiz/Career/Project/personal-assistant/frontend/lib/sse.ts).
