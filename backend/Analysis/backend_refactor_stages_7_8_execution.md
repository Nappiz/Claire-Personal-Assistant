# Pelaksanaan tambahan tahap 7â€“8

Scope diperluas oleh pemilik repository pada 13 September 2026 dari tahap 5â€“6 ke tahap 5â€“8.
Aturan REFACTORING_RULES.md dan roadmap tetap berlaku; frontend, schema, data, prompt,
provider, ranking, lease, dan retry tidak diubah.

## Tahap 7 â€” runtime

main.py -> workers/{maintenance,memory_outbox,summary,vector_reindex}_worker.py,
application/memory/run_maintenance.py, infrastructure/runtime.py,
infrastructure/persistence/legacy_schema.py, observability/log_buffer.py.
Interval 3600/60/60 detik, limit 25/20, serta reindex sebelum warmup dipertahankan.
Shutdown tetap membatalkan empat task dan kini menguras cancellation melalui gather
dalam finally; tidak menambah write atau mengganti retry policy.
Baseline tahap 5â€“6: 198 tes lulus. Setelah ekstraksi: 205 tes lulus.
Rollback: revert commit tahap 7; tidak membutuhkan rollback data.

## Tahap 8 â€” hardening

Pindahkan implementasi web dan telemetry dari services ke adapter dengan satu owner;
migrasikan seluruh consumer runtime ke wiring baru. Tambahkan CI boundary/cycle check,
evaluasi deterministik offline, dan manifest telemetry tanpa prompt/data pribadi.
Facade dihapus hanya jika semua consumer termasuk script audit sudah bermigrasi.
Script audit lokal yang belum dilacak tidak boleh dibuang atau diam-diam dirusak.
Owner compatibility: maintainer backend; kriteria penghentian: nol consumer legacy
pada runtime, tes, dan audit/tools, dengan contract suite tetap hijau.

