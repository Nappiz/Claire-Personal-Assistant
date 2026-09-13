# Bugfix keandalan web search dan protokol tool

Tanggal: 2026-09-13. Otorisasi: "langsung aja perbaiki", setelah diagnosis
halusinasi fakta aktual, hasil pencarian tidak terkait dan JSON action yang
terlihat sebagai jawaban. Checkpoint sebelum fix: 081d5b6 pada branch
codex/backend-stages-5-8. Ini perubahan perilaku tersendiri, bukan refactor
struktural atau kelanjutan tahap roadmap.

REFACTORING_RULES.md dan enterprise_backend_refactor_plan.md telah dibaca.
Pengecualian preserve-behavior dibatasi pada kebutuhan web search, query,
penerimaan bukti, forwarding teks tool, dan jawaban ketika bukti tidak tersedia.
Provider/model, mesin pencari Google, prompt bytes/tool schema, data/schema DB,
retrieval vector/graph dan frontend tidak diubah.

## Penyebab

- Planner memakai tool_choice auto untuk semua pertanyaan. Model boleh
  menjawab harga atau fakta terbaru tanpa benar-benar mencari.
- Fallback hanya aktif pada kata cari/google dan memakai kalimat mentah,
  termasuk instruksi percakapan yang bukan target query.
- TF-IDF hanya mengurutkan; hasil dengan overlap nol tetap diterima.
- JSON action/action_input merupakan content biasa, bukan native tool_calls.
  Streaming langsung meneruskannya dan menganggapnya jawaban selesai.
- SearXNG dapat membalas HTTP 200 dengan results kosong dan
  unresponsive_engines, tetapi backend menganggapnya pencarian tanpa hasil.

Probe read-only lokal ke http://127.0.0.1:8088/search dengan query publik
"harga pertamina" mengembalikan Google **Suspended: CAPTCHA**, tanpa hasil.
Ini hambatan live retrieval yang terpisah dari bug aplikasi. Tidak ada
panggilan LLM berbayar atau pengiriman konteks pribadi pada probe tersebut.

## Perubahan

1. intent_policy mendeteksi permintaan pencarian eksplisit dan kategori umum
   fakta berpotensi berubah: harga/tarif/kurs/cuaca/berita dan penanda waktu
   aktual. Tidak memakai daftar brand, game, hero, harga atau domain sumber.
2. Planner memaksa native web_search ketika turn membutuhkan web dan belum
   mencari. Bentuk parameter mengikuti
   [OpenAI Docs: Chat Completions tool_choice](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).
   Jika provider mengabaikan parameter atau menghasilkan planner kosong,
   backend tidak meneruskan jawaban tersebut dan menggunakan fallback terbatas.
3. Query fallback membuang wrapper percakapan dan permintaan "di internet".
   Query/goal model yang tidak cocok dengan target user terbaru diganti dengan
   target yang bersih. Rewrites acronym/plural biasa tetap diperbolehkan.
4. Potential JSON/fenced output ditahan sampai bisa diperiksa. Complete
   assistant planner envelope action web_search yang valid dapat dipakai
   sebagai rencana fallback. Backend tidak membuat native tool-call/signature
   palsu dan tidak mengirim ulang envelope sebagai tool history.
5. Action lain tidak dieksekusi. JSON dari user, memory atau halaman web tidak
   pernah diperiksa sebagai sumber instruksi eksekusi. read_url tetap memakai
   native tool path dan allowlist existing; textual read_url hanya ditolak/
   masuk recovery, bukan diberi kemampuan baru.
6. Prose biasa tetap streaming dan whitespace dipertahankan. JSON jawaban
   non-tool dipertahankan. Envelope tool pada final answer tidak dieksekusi
   atau ditampilkan; recovery existing maksimal satu kali, lalu pesan batas
   yang jujur bila provider terus mengirim output tidak valid.
7. Filter evidence terpisah dari ranking, diterapkan terhadap query yang
   benar-benar mengambil tiap result. Query multi-topik membutuhkan minimal
   dua anchor; kecocokan hanya lokasi tidak cukup. Result bertanggal lebih
   lama daripada tahun eksplisit query ditolak. Ranker TF-IDF tidak ditulis ulang.
8. Query translations tetap dinilai terhadap query masing-masing, bukan wajib
   memiliki overlap dengan research_goal yang berbeda bahasa.
9. HTTP-200 results kosong ditambah unresponsive_engines diklasifikasikan sebagai
   engine failure/unavailable, bukan "tidak ada hasil relevan".
10. Bila web disabled/unavailable/no_results atau status ok tanpa result,
    jawaban fakta tidak diteruskan. Backend mengirim batas yang spesifik dan
    tetap menghasilkan usage/completion existing.

Scope internal project tetap diproteksi, termasuk detail terbaru milik project.
Pertanyaan harga layanan publik "untuk project ..." tetap boleh mencari karena
project adalah konteks penggunaan, bukan objek riset. Ambiguous scope tidak
dibuka. Bound satu search, round/read limits, allowlist URL, provider metadata,
retry opening, deadline dan accounting kumulatif tetap dipertahankan.

## Verifikasi

Baseline relevan: **36/36** tes web, stream, replay dan project scope lulus.
Tujuh tes baru pada implementasi awal gagal (11 failures termasuk subtests),
membuktikan contoh pengguna belum terlindungi oleh suite lama.

Hasil akhir:

- Full backend: **241/241 lulus**, tanpa skipped.
- Eval web-search-reliability-v1: **109/109 lulus**, enam kelompok fidelity 1.0.
- 16 tes regresi baru mencakup harga/fakta terbaru, query bersih, hasil tidak
  terkait, periode lama, overlap hanya lokasi, CAPTCHA, JSON split/fenced/
  terpotong, native forced search diabaikan, unknown action, bounded recovery,
  scope private dan query topik lama.
- Architecture: 209 module, 407 edge; nol cycle dan nol violation.
- git diff --check dan compileall file terkait lulus.
- Frozen prompt/request, API/OpenAPI, vector/graph fixtures tidak diregenerasi.
- Source proof vector/graph tetap lulus; 39 fungsi memory, web reader dan
  telemetry tetap identik terhadap checkpoint refactor.
- Source proof historical LLM memiliki tiga expected differences:
  web_tools_allowed_for_turn, web_search_plan_from_call dan
  generate_chat_response_stream. Web proof memiliki dua: plan_web_search dan
  retrieve_web_context. Verifier tidak diubah untuk menyembunyikan perubahan ini.

Dua assertion intent lama diperbarui karena memang mengharuskan raw query dan
explicit-only search yang sekarang diubah secara sengaja. Full suite juga
menemukan guard scope yang terlalu luas terhadap harga layanan publik untuk
project; implementasi diperbaiki, assertion existing dipertahankan.

Seluruh suite memakai storage terisolasi/fake provider dan blocked network.
Tidak ada perubahan data pengguna. Tidak tersedia formatter/linter/type-checker
tambahan di runtime repo. Tidak dilakukan paid live-model eval, load/soak test
atau pengukuran kualitas jawaban produksi.

## Batasan yang tidak boleh disembunyikan

- Intent masih generic heuristic, bukan pemahaman semantik sempurna. Ada
  kemungkinan false positive/negative pada kalimat yang tidak tercakup.
- Filter lexical/provenance bukan pembuktian semantik atau jaminan nol
  halusinasi. Synonym-only result dapat ditolak; halaman yang cocok secara
  lexical belum otomatis membuktikan semua klaim/nilai harga yang dibuat model.
- Freshness filter memakai tahun yang eksplisit dalam query dan tanggal yang
  terlihat pada result. Result tanpa tanggal tidak dianggap pasti mutakhir;
  verifikasi harga/wilayah/periode tetap memerlukan bukti sumber.
- Potential JSON/fenced answers menunggu inspeksi sebelum ditampilkan;
  first-delta timing prose normal tetap diuji oleh suite streaming existing.
- Google/SearXNG CAPTCHA belum dipulihkan oleh perubahan kode ini. Jangan
  menyatakan pencarian live sudah sehat atau quality production sudah teruji.
  Tidak dilakukan CAPTCHA bypass, restart container, config change, atau
  perpindahan mesin pencari/provider tanpa keputusan tersendiri.

## Rollout dan rollback

Restart backend, lalu cek pertanyaan konseptual, harga produk, daftar terbaru,
JSON tool yang tidak valid, serta detail internal project. Saat Google masih
suspended, hasil yang benar adalah pemberitahuan layanan belum tersedia,
bukan harga/daftar terbaru hasil tebakan.

Untuk memulihkan live retrieval, Google/SearXNG perlu kembali sehat atau perlu
otorisasi fallback mesin pencari. Itu keputusan operasional terpisah.

Rollback: revert commit bugfix capability ini. Tidak ada migration/reindex/reset
data. Checkpoint 081d5b6 menyimpan implementasi sebelum perubahan ini; laporan
refactor dan streaming sebelumnya tetap merupakan bukti checkpoint historis.
