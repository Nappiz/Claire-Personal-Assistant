# Compatibility retirement register

Folder ini **bukan layer production**. Semua implementasi telah memiliki satu owner
di app/domain, app/application, app/infrastructure, atau app/observability.
Production bootstrap/API/worker tidak mengimpor services; CI menolak regresi itu.

Owner: maintainer backend. Review penghapusan berikutnya: **1 Oktober 2026**.
Tanggal ini adalah checkpoint review, bukan izin menghapus consumer yang belum migrasi.

| Facade | Owner implementasi | Consumer tersisa |
| --- | --- | --- |
| llm_service | domain/llm + infrastructure/llm/composition + application workflows | Tes legacy; script audit AI |
| memory_service | infrastructure/memory/composition + application workflows | Tes legacy; script audit AI |
| qdrant_service | infrastructure/vector | Tes legacy; script audit embedding |
| neo4j_service | infrastructure/graph | Tes legacy; script audit/repair graph |
| web_search_service, web_reader_service | domain/web + infrastructure/web | Tes legacy; script audit AI |
| ai_usage_service | observability/ai_telemetry | Tes accounting legacy |
| memory_policy, location_grounding, diagnostic_service | domain/graph, domain/llm, domain/diagnostics | Tes legacy; script audit/repair |

Sudah dihapus: settings_service (nol consumer Python); legacy_bridges production
diganti application_wiring (bukan facade). routes/chat_routes dan settings_routes
juga hanya adapter compatibility untuk tes/audit; main memakai app/api langsung.

Kriteria penghapusan setiap facade:

1. Migrasikan import, pemanggilan helper, dan patch target tes/audit ke owner nyata.
2. Pertahankan assertion/fixture; jangan regenerasi golden fixture supaya migrasi lolos.
3. Pastikan pencarian seluruh backend (termasuk Analysis dan tool lokal) nol consumer.
4. Jalankan suite, HTTP/SSE contracts, eval offline, dan architecture gate.
5. Hapus facade dalam commit tersendiri; jangan membuat facade baru sebagai pengganti.

Audit/repair live tidak dijalankan otomatis: beberapa tool itu menulis data lokal.
Facade tersisa hanya mendelegasikan; tidak ada implementasi algoritma kedua.
