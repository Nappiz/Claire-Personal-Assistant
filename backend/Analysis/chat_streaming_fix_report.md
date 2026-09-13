# Perbaikan streaming planner / direct answer

Tanggal: 2026-09-13. Scope: satu bug perilaku chat backend, bukan refactor
struktural lanjutan. Otorisasi pemilik: "perbaiki aja", setelah diagnosis
bahwa jawaban planner diterima lengkap lalu dikirim sebagai satu delta.
Checkpoint sebelum perbaikan: branch codex/backend-stages-5-8, commit 2dde329.
REFACTORING_RULES.md dan enterprise_backend_refactor_plan.md sudah dibaca.

## Penyebab dan perubahan

Planner sebelumnya tidak memakai stream=True. Saat model menjawab tanpa tool,
backend menggunakan kembali jawaban itu agar tidak membayar generasi kedua,
tetapi baru mengirim satu event delta setelah seluruh respons diterima.
Jalur ini sudah ada pada baseline sebelum refactor; bukan akibat pemindahan
modul. Parser SSE frontend sudah membaca delta bertahap dan tidak diubah.

Planner kini memakai stream=True dan stream_options.include_usage=True.
Visible content diteruskan langsung, termasuk whitespace, tanpa artificial
typing delay dan tanpa generasi kedua untuk jawaban langsung. Jawaban lengkap
tidak dikirim ulang setelah stream selesai.

Fragment tool-call digabung menurut index; arguments/nama yang terpotong
dirakit sebelum tool dijalankan. Index tidak dikirim ulang dalam tool history.
Opaque provider metadata, termasuk extra_content/google/thought_signature,
dipertahankan sebagai nilai asli, bukan digabung sebagai potongan teks.
Penggabungan berbasis index mengikuti
[panduan function-calling OpenAI](https://developers.openai.com/api/docs/guides/function-calling#streaming).
Ini merupakan penggunaan skill OpenAI Docs dalam implementasi.

Jika provider mengirim visible preamble sebelum tool-call diketahui, teks itu
dapat tampil lebih awal; setelah tool terdeteksi, konten planner tidak diteruskan
sebagai jawaban. Field reasoning_content tidak pernah diteruskan sebagai delta.
Event ringkasan web tetap dihasilkan setelah loop planner. Dengan demikian
timing delta relatif terhadap ringkasan web dapat lebih awal daripada baseline.

Usage kumulatif planner dihitung sekali, termasuk usage-only tail chunk; setiap
invocation ID tetap tercatat satu kali. Status length tetap incomplete.
Deadline planner tetap memakai batas konfigurasi yang sama, dihitung sejak
panggilan dibuka sampai pembacaan stream selesai. Deadline tidak bergantung
pada timeout context yang bertahan melintasi yield antar-task.

Stream ditutup saat selesai, disconnect, cancellation, atau error. Client
tetap ditutup oleh finally use case induk. Setelah visible text sudah dikirim,
error/timeout diteruskan ke penanganan error existing; backend tidak menambahkan
jawaban fallback kedua ke jawaban parsial. Error sebelum visible text tetap
memakai fallback bersih yang sudah ada.

## Kontrak yang dipertahankan

- Endpoint, schema request/response dan bentuk payload/event SSE.
- Prompt bytes, tool schema, provider/model selection, temperature planner
  0.0 dan final answer 0.7, max_tokens, konfigurasi deadline serta retry opening.
- Search satu kali, URL allowlist, batas baca/round, deduplication dan tool replay.
- Urutan lifecycle turn, persistence, outbox, retry/cancel serta data/schema DB.
- Gateway normalization dan owner telemetry existing; tidak ada dependency baru.

Perubahan yang disengaja: request planner streaming, timing/fragmentasi delta,
dan larangan regenerasi setelah jawaban parsial terlanjur tampil. Ini terpisah
dari checkpoint refactor struktural dan tidak boleh diklaim sebagai body-identical
refactor.

## Modul

- application/chat/stream_planning_response.py: satu invokasi planner streaming,
  forwarding delta, deadline dan accounting.
- domain/llm/planning_stream.py: accumulator provider-neutral dan payload replay.
- execute_web_tool_loop.py: memakai hasil stream sebelum menjalankan tool.
- stream_response.py: tidak mengulang jawaban yang sudah dikirim.
- Dua file regression test baru dan penyesuaian tiga file tes existing agar
  memeriksa gabungan delta, bukan mewajibkan satu batas chunk.
- Manifest eval diperluas menjadi chat-streaming-fix-v1; frozen prompt/API/graph
  fixtures tidak diregenerasi. Laporan checkpoint refactor lama tetap historis.

## Verifikasi

Baseline relevan sebelum implementasi: 26/26 tes tool-loop dan medium 11-16
lulus. Lima tes streaming baru gagal pada implementasi lama yang masih membuka
generasi kedua alih-alih menggunakan planner stream; setelah fix lulus.

- Seluruh backend: **225/225 lulus**, tanpa skipped.
- Eval offline: **93/93 lulus**, enam kelompok fidelity 1.0.
- Tes tambahan: first delta sebelum provider selesai, satu generasi, whitespace,
  cumulative usage, length/incomplete, disconnect, cancellation saat menunggu,
  error/timeout setelah partial answer, fallback sebelum text, fragmen dua
  tool-call, metadata replay, invalid index, dan terminal telemetry lewat gateway.
- Architecture: 207 module / 397 edge; nol cycle dan nol violation.
- git diff --check lulus.
- Source proof vector/graph dan web/telemetry tetap lulus.
- Source proof LLM/memory terhadap checkpoint tahap 0-4: satu expected difference
  pada generate_chat_response_stream, nol pada 39 fungsi memory. Verifier tidak
  diubah atau dilemahkan untuk menutupi perubahan perilaku yang diotorisasi ini.

Full suite pertama menemukan satu assertion lama yang mengharuskan seluruh
"Planner partial" berada dalam delta pertama. Assertion diperbarui hanya untuk
menggabungkan seluruh delta; jumlah call dan status incomplete tetap diperiksa.
Full suite berikutnya lulus. Tidak ada perubahan data pengguna atau frontend.

Semua tes memakai provider fake / SDK chunk / adapter existing dan storage
terisolasi, tanpa jaringan. Belum dilakukan provider-live test, load/soak test,
atau pengukuran latensi produksi. Formatter/linter/type checker tambahan tidak
tersedia pada runtime repo; arsitektur dan suite existing menjadi quality gate.

## Acceptance dan rollout

Restart proses backend agar implementasi baru dimuat. Coba satu pertanyaan
konseptual tanpa web dan satu pertanyaan yang membutuhkan search/read.
Jawaban langsung harus muncul bertahap sesuai chunk provider; jawaban tidak
berulang, tool tetap selesai sebelum hasil dipakai, dan completion terminal
tetap diterima. Kecepatan chunk tetap bergantung pada provider dan proxy.

Provider yang tidak mendukung kombinasi tool + streaming masih dapat masuk
fallback existing sebelum text, sehingga validasi provider live perlu dilakukan
sebelum menyatakan semua provider streaming. Tidak ada live-call berbayar atau
pengiriman konteks pribadi dilakukan sebagai bagian tes ini.

Rollback: revert commit capability streaming ini (bukan checkout seluruh
repository atau reset data). Checkpoint 2dde329 menyimpan perilaku sebelum fix;
tidak ada migration atau data setengah jadi yang perlu dibersihkan.
