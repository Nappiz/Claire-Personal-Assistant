# Perbaikan lokasi kampus/kantor, rujukan Adel, dan pencabutan domisili

Tanggal: **13 September 2026**. Ruang lingkup: tiga masalah yang dilaporkan pengguna setelah perbaikan M17/M18/L01. Perbaikan meliputi kode, tampilan graph, dan data lokal yang sumbernya sudah diperiksa.

## 1. Akar masalah dan perubahan

| Masalah | Bukti dan akar masalah | Perbaikan |
|---|---|---|
| Kota kampus/kantor menjadi domisili orang | Prompt ekstraktor melarang inferensi secara umum, tetapi belum menjelaskan attachment lokasi secara spesifik atau memverifikasinya dalam kode. Cached extraction pesan perkenalan berisi Nafiz `LIVES_IN` Surabaya/PIK. | `location_grounding.py` memeriksa klausa domisili terbaru sebelum mengizinkan `LIVES_IN`. Lokasi yang secara langsung melekat pada institusi dibuat sebagai institusi `LOCATED_IN` lokasi. |
| Adel yang diperkenalkan dalam pesan sama dianggap ambigu | Router memvalidasi entitas hanya terhadap history/summary. Pattern suffix `nya` juga mewajibkan mapping tambahan pada kata seperti `namanya` dan `tinggal nya`. | Pesan terbaru masuk discourse context; pemetaan nama eksplisit lokal didukung. “Temenku namanya Adel dia …” dan “si Adel itu dia …” mempunyai binding lokal yang jelas. Suffix pengantar nama/pelengkap predikat tidak mewajibkan antecedent tambahan. |
| Penolakan domisili dapat hilang dari hasil ekstraksi | Model dapat menghilangkan retraction, menghasilkan retraction tanpa target, atau menyalin fakta lama ketika pengguna hanya mengonfirmasi nama. | Guard membangun retraction spesifik orang/lokasi dari negasi eksplisit yang didukung. Reminder dengan negasi tetap masuk ekstraksi. Target Malang tidak mencabut Surabaya. |
| Relasi yang dicabut masih tampak pada graph terbuka | Saat pemeriksaan, Adel–Malang sudah `is_current=false`, sedangkan frontend hanya memuat graph ketika modal dibuka atau tombol reload ditekan. | Modal memantau perubahan pekerjaan memori; graph diperbarui setelah status/stage berubah, menggunakan `no-store`. Background refresh mempertahankan filter/posisi dan membersihkan detail relasi yang hilang. |

## 2. Semantik graph yang dihasilkan

| Ucapan | Relasi yang didukung |
|---|---|
| “Aku kuliah di ITS (…) di Surabaya” | Nafiz `STUDIED_AT` ITS; ITS `LOCATED_IN` Surabaya. Tidak mengizinkan Nafiz `LIVES_IN` Surabaya dari kalimat tersebut. |
| “Aku magang di Agung Sedayu Group di PIK” | Nafiz `INTERNS_AT` Agung Sedayu Group; organisasi `LOCATED_IN` PIK. Tidak mengizinkan Nafiz `LIVES_IN` PIK dari kalimat tersebut. |
| “Temenku namanya Adel dia kuliah di UB (…) di Malang …” | Rujukan “dia” dapat diikat ke Adel dalam pesan itu sendiri. Adel `STUDIED_AT` UB; UB `LOCATED_IN` Malang; assertion semester kedua orang tetap tersedia. |
| “Si Adel itu dia tinggal nya di Surabaya sih gak di Malang” | Adel `LIVES_IN` Surabaya; retraction Adel `LIVES_IN` Malang. |
| “Inget loh ya si Adel itu gak tinggal di Malang” | Retraction spesifik Adel–Malang, termasuk bila provider mengembalikan extraction kosong dan identity context dapat diikat secara aman. |

Kontrak tipe sekarang membedakan `LIVES_IN` Person → Location, `LOCATED_IN` institusi/Location → Location, dan `INTERNS_AT` Person → organisasi. Untuk klausa magang eksplisit, drift `WORKS_AS` dengan target organisasi dibetulkan menjadi `INTERNS_AT`; fakta pekerjaan lain tidak dihapus hanya karena ada magang.

Identity context `temen nafiz`, `temenku`, `temanku`, dan `my friend` dinormalisasi ke pembeda `teman nafiz`. Pembeda yang berbeda, seperti teman kuliah versus teman kerja, tetap dibedakan. Nama saja tidak menjadi dasar untuk menggabungkan orang.

## 3. Pencabutan yang bertahan terhadap write terlambat

Retraction domisili tanpa fact ID membuat marker `ResidenceRetraction` berdasarkan source, scope, dan target. Marker dibuat di bawah fence source dalam transaksi yang sama. Write `LIVES_IN` yang event time-nya tidak lebih baru daripada marker tidak dapat mengaktifkan fakta, termasuk jika edge belum ada saat negasi diproses.

Penegasan domisili yang benar-benar lebih baru tetap diizinkan. Retraction dengan fact ID mempertahankan scope fact ID tersebut. Target yang tidak dapat di-resolve tidak berubah menjadi pencabutan semua target. Confidence retraction dibatasi juga oleh confidence node source/target, sehingga identitas yang tidak pasti tidak dapat mencabut fakta valid.

Marker bukan node `Entity`, sehingga tidak muncul sebagai entitas memori dalam visualisasi. Constraint key unik dibuat melalui bootstrap Neo4j yang sudah tersedia; tidak ada migrasi Alembic baru untuk pekerjaan ini.

## 4. Perbaikan data lokal yang sudah dijalankan

Tiga source message diperiksa melalui SQLite dan provenance Neo4j sebelum perubahan. Repair menolak source yang berubah, job yang belum selesai/tombstoned, atau fakta yang memiliki evidence tambahan di luar source yang telah diperiksa.

Hasil penerapan:

- **3 cached extraction diperbaiki**, menghapus **5 edge salah** dari cache.
- **3 fakta aktif dinonaktifkan:** Nafiz–Surabaya, organisasi UB `LIVES_IN` Malang, dan Nafiz `WORKS_AS` organisasi Agung Sedayu Group.
- Nafiz–PIK dan Adel–Malang sudah nonaktif ketika diperiksa; status tersebut dipertahankan.
- **4 relasi baru diverifikasi aktif:** ITS `LOCATED_IN` Surabaya, Agung Sedayu Group `LOCATED_IN` PIK, Nafiz `INTERNS_AT` Agung Sedayu Group, dan UB `LOCATED_IN` Malang.
- **Adel `LIVES_IN` Surabaya tetap aktif.** Domisili Nafiz di BSD yang berasal dari assertion terpisah juga tetap aktif.
- Dry-run kedua menemukan **0 perubahan**, tanpa duplicate tambahan.

Invalidation dijalankan melalui endpoint pengelolaan fakta pada backend yang sedang berjalan agar status evidence SQLite dan vector ikut diperbarui. Cached extraction dibetulkan dengan compare-and-set, kemudian relasi grounded diproyeksikan ke graph menggunakan event time asli. Raw percakapan tidak ditulis ulang. Evidence bundle lama yang mengandung fakta salah mengikuti mekanisme karantina per source yang sudah tersedia; perbaikan ini tidak mengaktifkan ulang seluruh bundle tersebut.

Backup sebelum perubahan: [location_20260913T065335269945Z.json](D:/Nafiz/Career/Project/personal-assistant/backend/data/repairs/location_20260913T065335269945Z.json). Script repair dibatasi pada tiga source yang diperiksa, bukan pembersih seluruh arsip: [ai_location_repair_reported_data.py](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_location_repair_reported_data.py). Default script adalah dry-run; `--apply` mengubah data setelah validasi dan backup.

Fakta nonaktif tetap dapat disimpan sebagai riwayat/provenance di database. Endpoint graph default mengecualikannya; status nonaktif tidak berarti record fisiknya harus dihapus.

## 5. Pengujian dan batas interpretasi

| Pemeriksaan | Hasil |
|---|---|
| Suite backend lengkap | **161 tes lulus**, termasuk **18 regresi baru** lokasi/rujukan |
| Suite lokasi setelah pembatasan history grounding terakhir | **18/18 lulus** |
| Neo4j native | **6 pemeriksaan lulus**, termasuk correction, stale replay, negasi sebelum edge pertama, penegasan lebih baru, confidence identitas, dan write/negasi concurrent |
| Cleanup fixture native | Terverifikasi; hanya key UUID fixture yang dicocokkan |
| Frontend TypeScript | `tsc --noEmit` lulus |
| Frontend lint terkait | `eslint components/GraphVisualizer.tsx` lulus |
| Repair data nyata | Invalidation dan empat tambahan terverifikasi; dry-run ulang nihil perubahan |

Pengujian: [test_location_and_inline_reference_fixes.py](D:/Nafiz/Career/Project/personal-assistant/backend/tests/test_location_and_inline_reference_fixes.py). Native graph: [ai_location_native_graph_checks.py](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_location_native_graph_checks.py). Pemeriksaan sumber read-only: [ai_location_read_checks.py](D:/Nafiz/Career/Project/personal-assistant/backend/Analysis/ai_location_read_checks.py).

**Batasan:** guard bersifat konservatif untuk pola bahasa yang didukung, bukan parser universal. Bentuk ambigu/koordinasi subjek tidak dipaksa menjadi fakta. Kutipan, hipotesis, rencana, dan domisili historis tidak diubah menjadi `LIVES_IN` current melalui guard. Rujukan yang hanya ada di luar konteks terbatas tetap dapat memerlukan klarifikasi. Pengujian provider menggunakan mock, bukan evaluasi precision/recall pada model hidup; tidak ada request AI berbayar untuk pengujian atau repair ini. Frontend diverifikasi melalui tipe/lint, bukan uji interaksi browser otomatis.

Polling status berjalan saat modal graph terbuka, sekitar tiga detik pada tab terlihat dan lebih jarang ketika tersembunyi. Graph tidak dicari ulang pada setiap polling yang statusnya tidak berubah. Hasil masih mengikuti waktu penyelesaian worker memori; generation chat tetap tidak menunggu seluruh external memory write.

## 6. File dan pengoperasian

Implementasi utama: [location_grounding.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/location_grounding.py), [llm_service.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/llm_service.py), [memory_policy.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_policy.py), [memory_service.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/memory_service.py), [neo4j_service.py](D:/Nafiz/Career/Project/personal-assistant/backend/services/neo4j_service.py), dan [GraphVisualizer.tsx](D:/Nafiz/Career/Project/personal-assistant/frontend/components/GraphVisualizer.tsx).

Restart backend dan reload frontend agar proses yang berjalan menggunakan seluruh perubahan. Perbaikan data lokal sudah diterapkan; tidak perlu menghapus sesi atau mengulang perkenalan untuk menghapus fakta salah yang telah dinonaktifkan.
