# Implementasi Perbaikan Temuan HIGH Audit Komponen AI

Tanggal verifikasi: 2026-09-12  
Sumber audit: `ai_components_extreme_audit_2026-09-12.md`

## Status

Seluruh temuan H01-H12 telah ditangani. Perubahan dibatasi pada jalur chat AI, retrieval, memory outbox, graph/vector memory, ringkasan percakapan, lifecycle session, serta kontrak request frontend yang terkait langsung.

| ID | Perbaikan yang diterapkan | Verifikasi utama |
|---|---|---|
| H01 | Pekerjaan maintenance, retry outbox, reindex, dan retry ringkasan yang sinkron dijalankan melalui worker thread; jalur request memakai threadpool untuk operasi sinkron. | Regression test memastikan loop terjadwal memakai `asyncio.to_thread`. |
| H02 | Router, resolusi scope, Qdrant, dan Neo4j berbagi satu deadline monotonic ujung-ke-ujung. Internal memory LLM memakai timeout total dan tanpa retry SDK tersembunyi. | Simulasi router/scope lambat selesai dalam deadline, dengan status degraded eksplisit. |
| H03 | Commit chat dan pembuatan outbox dilakukan sebelum event `done`; pemrosesan external memory berjalan setelahnya dan tidak dapat mengganti jawaban sukses dengan internal error. | Test stream memastikan kegagalan memory tidak menghapus jawaban sukses. |
| H04 | Claim outbox menjadi atomic compare-and-set dengan `lease_token` dan `lease_expires_at`. Semua update/finalisasi tahap memakai token sebagai fencing condition. | Claim kedua ditolak selama lease aktif; claim setelah expiry mendapat token baru. |
| H05 | Penghapusan session memakai durable soft tombstone sebelum cleanup eksternal. Worker memeriksa tombstone setelah setiap write dan menjalankan compensating cleanup bila write melintasi deletion. | Simulasi delete saat Qdrant upsert memastikan kompensasi terpanggil. |
| H06 | Seluruh node merge, conflict check, edge merge, supersession, dan retraction dijalankan dalam satu Neo4j write transaction. Source entity dikunci sebelum keputusan cardinality. | Fake driver memastikan hanya satu `execute_write` dan fence query terjadi. |
| H07 | Outbox menyimpan `event_at` dari waktu asli user turn. Ekstraksi, TTL, conflict resolution, supersession, dan retraction memakai event time; event lama dikarantina dan tidak menaikkan importance. | Test retry memastikan timestamp 2020 tetap diteruskan ke extractor dan graph saat diproses kemudian. |
| H08 | Schema ekstraksi mendukung `retractions` berdasarkan source/relation dengan target atau `fact_id`, sehingga fakta dapat dicabut tanpa membuat edge pengganti palsu. | Test retraction-only menonaktifkan fact lama tanpa positive replacement edge. |
| H09 | Qdrant memiliki `memory_status`; hasil inactive difilter. Status authoritative juga disimpan di SQLite dan diperiksa saat retrieval, sehingga payload Qdrant lama/terlambat tidak lolos. Supersession, retraction, dan koreksi operator mempropagasi invalidasi. | Test graph invalidation mengubah sumber message menjadi inactive dan memanggil update payload Qdrant. |
| H10 | Ringkasan memakai `summary_version`, `summary_through_sequence`, `summary_pending`, batch berbasis token, dan optimistic compare-and-swap terhadap checkpoint serta `next_turn_sequence`. Retry terjadwal memproses ringkasan yang tertunda. | Simulasi turn konkuren membuat stale summarizer kalah tanpa menimpa summary. |
| H11 | Setiap turn mempunyai UUID durable, sequence, status, dan lease. User message disimpan sebelum provider I/O. Retry ID yang sama menggunakan message/sequence yang sama; completed retry mengembalikan jawaban cache; turn berbeda ditolak selama lease aktif. Frontend mempertahankan UUID yang sama saat failover provider. | Test mencakup conflict, interruption, retry, commit idempotent, dan cached replay. |
| H12 | Prompt dibatasi dengan anggaran token konservatif. User input, vector facts, graph facts, summary, web payload, history, dan output token mempunyai batas eksplisit. | Stress test dengan ratusan message dan payload sangat besar tetap berada di bawah budget input. |

## Perubahan Data

Migrasi `a9c2f604d812` menambahkan metadata turn, lease, event time, tombstone, lifecycle vector, serta checkpoint ringkasan. Jalur kompatibilitas SQLite lokal juga melakukan penambahan kolom/index dan backfill `event_at` serta `turn_sequence` untuk database lama.

## Hasil Verifikasi

- Backend: 77 unittest lulus.
- Regression khusus H01-H12: 11 test lulus.
- Alembic: upgrade seluruh chain, downgrade satu revision, lalu upgrade kembali ke `a9c2f604d812` lulus pada database sementara.
- Neo4j lokal: delapan query untuk node merge, conflict check, fact merge, supersession, replacement, dan retraction berhasil divalidasi dengan `EXPLAIN`; tidak ada mutasi yang dieksekusi.
- Frontend: TypeScript `--noEmit` lulus.
- Frontend file yang berubah: ESLint lulus untuk `app/chat/page.tsx` dan `lib/sse.ts`.
- Seluruh 63 source Python di luar virtualenv berhasil diparse.

Lint frontend penuh masih melaporkan dua error lama pada `BackendLogsModal.tsx` dan `SystemStatsModal.tsx`; keduanya berada di luar komponen dan file yang diubah untuk temuan HIGH ini.
