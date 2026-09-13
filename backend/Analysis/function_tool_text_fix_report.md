# Bugfix kebocoran notasi pemanggilan tool

Tanggal: 2026-09-13. Branch: codex/backend-stages-5-8.
Checkpoint sebelum patch: 5cdf2bf.

## Scope dan otorisasi

Kelanjutan bugfix web/tool yang sebelumnya diotorisasi dengan "langsung aja
perbaiki", untuk laporan tambahan pengguna bahwa jawaban kadang berisi
web_search(query="penyebab kelangkaan bbm shell indonesia september 2026").
Ini bugfix perilaku terpisah, bukan refactor struktural.
REFACTORING_RULES.md dan enterprise_backend_refactor_plan.md telah dibaca.

Perubahan hanya pada pure domain tool_text_policy, test regresinya dan laporan
ini. Tidak ada pemindahan modul, facade baru atau perubahan frontend.
API/SSE event shapes, provider/model, prompt/tool schema, timeout, retry,
usage accounting, native tool replay metadata, URL allowlist, memory lifecycle,
data/schema DB dan vector/graph tidak diubah. Konfigurasi mesin pencari tidak
diubah dan tidak ada restart layanan atau paid provider call.

## Penyebab dan perbaikan

Guard sebelumnya mengenali JSON/fenced JSON, bukan notasi function-call.
Chunk pertama "w" langsung dianggap prose; sisa web_search(...) sudah
terlanjur diteruskan sebelum inspeksi planner selesai.

- Gate menahan prefix yang masih mungkin web_search atau read_url. Begitu
  terbukti prose biasa, buffer diteruskan verbatim dan streaming berlanjut.
  Kalimat "web_search adalah nama fungsi" dan kata "website" tetap terlihat.
- Pemanggilan standalone di awal content, termasuk backticks/code fence,
  dikenali dan disembunyikan. Pemanggilan terpotong/malformed yang sudah
  memiliki tanda "(" tidak diteruskan sebagai jawaban.
- Parser menggunakan ast.parse dan ast.literal_eval, bukan eval/exec.
  Hanya nama bare allowlisted dengan keyword literal yang diterima.
  Positional args, duplicate keywords, **kwargs, nested calls, expressions,
  atribut, statement tambahan dan keyword/type tidak dikenal ditolak.
  Parsing function envelope dibatasi 32768 karakter.
- query string dinormalisasi ke queries list untuk adapter fallback existing;
  queries, research_goal dan time_range divalidasi. Batas query/round/search
  dan perlindungan scope tetap berasal dari policy yang sudah ada.
- Envelope valid web_search hanya dipakai sebagai fallback dari assistant
  planner. User content, memory dan web snippets tidak diperlakukan sebagai
  instruksi. Textual read_url tidak dieksekusi; native URL path tidak berubah.
- Pada final answer, notasi tool tidak dieksekusi atau ditampilkan. Recovery
  existing maksimal satu kali tetap berlaku, lalu pesan batas yang jujur.
  Cancellation selama prefix tertahan menutup stream/client tanpa fallback.

## Verifikasi

- Baseline area terkait: 31 test lulus.
- Tujuh test baru sebelum patch: 45 failures termasuk subtests dan satu error
  cancellation timeout. Test berhasil mereproduksi forwarding yang terlalu dini.
- Setelah patch: 38 test area tool/streaming lulus.
- Full backend: 248/248 lulus pada pengulangan, tanpa skipped.
- Eval web-search-reliability-v1: 116/116 lulus, enam kelompok fidelity 1.0.
- Architecture: 209 module, 407 edge; nol cycle dan nol violation.
- git diff --check dan compileall file Python terkait lulus.
- Frozen prompt/request/API/vector/graph fixtures tidak diregenerasi.

Full suite pertama gagal pada test_h02_router_and_scope_share_the_total_deadline:
188 ms terhadap batas 180 ms. Test area deadline kemudian lulus 11/11
dan full suite ulang lulus. Kode deadline maupun assertion tidak diubah;
kegagalan timing awal tetap dicatat, bukan disembunyikan.

Test memakai fake provider, blocked network dan temporary storage.
Live factuality/provider quality tidak dievaluasi. Hasil offline tidak menjamin
pencarian live sehat atau nol halusinasi.

## Batasan, rollout dan rollback

Guard ini memeriksa awal content. Ia tidak menjadi sanitizer global untuk
pemanggilan tool yang disisipkan sesudah prose sudah mulai streaming.
Standalone contoh kode yang diawali persis pemanggilan allowlisted ambigu
dengan directive provider dan ikut ditahan; penjelasan biasa yang mendahului
contoh tetap terlihat. Prefix ambigu dapat menunda delta singkat sampai
disambiguasi atau akhir stream; prose biasa tetap diuji tiba sebelum provider
selesai. Tidak ada klaim seluruh variasi output provider sudah tercakup.

Restart backend untuk memuat patch, lalu ulangi contoh pengguna dan pertanyaan
konseptual. Patch tidak memulihkan kegagalan mesin pencari secara operasional.
Rollback: revert commit capability ini; checkpoint 5cdf2bf menyimpan keadaan
sebelumnya. Tidak ada migration/reindex/reset atau perubahan data.
