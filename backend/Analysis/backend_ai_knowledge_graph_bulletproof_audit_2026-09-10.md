# Audit Backend Claire AI & Knowledge Graph

> Tanggal audit: 10 September 2026  
> Konteks deployment: personal assistant untuk Nafiz, berjalan lokal. Hanya API LLM yang berada di luar mesin lokal.  
> Fokus: ketepatan perilaku Claire, kualitas ingatan, integritas knowledge graph, retrieval, extraction, dan lifecycle memory.  
> Di luar scope: optimasi latency, throughput, efisiensi, concurrency, autentikasi untuk deployment publik, dan keamanan multi-user.

## Verdict

Tidak ditemukan issue **Critical** pada implementasi saat ini.

Raw conversation masih tersimpan di SQLite, memory write sudah memakai durable outbox, setiap fact baru memiliki provenance, dan tersedia endpoint koreksi granular. Karena itu, issue yang ditemukan belum memenuhi ambang Critical berupa korupsi menyeluruh yang tidak dapat dipulihkan, kehilangan sumber data utama, atau kegagalan yang pasti mengenai seluruh sistem.

Namun, sistem belum dapat disebut bulletproof secara semantik. Ada beberapa jalur yang dapat membuat Claire mengingat fakta yang salah, mempertahankan keadaan lama sebagai keadaan sekarang, atau kehilangan seluruh long-term memory secara diam-diam pada suatu turn.

| Severity | Jumlah | Kesimpulan |
|---|---:|---|
| Critical | 0 | Tidak ada yang terbukti memenuhi ambang Critical. |
| High | 5 | Ada risiko sistemik terhadap freshness, kebenaran fact, grounding, dan availability memory. |
| Medium | 8 | Ada false negative extraction, fragmentasi entity, retrieval noise, dan context loss yang material tetapi lebih terbatas. |
| Low | 4 | Ada edge case dan diagnostic gap dengan dampak lebih kecil. |

## Definisi Severity

- **Critical**: menyebabkan korupsi atau kehilangan knowledge secara luas dan sulit dipulihkan, atau membuat seluruh Claire selalu salah/tidak dapat dipakai pada jalur normal.
- **High**: dapat membuat fungsi inti personal assistant—mengingat dan menjawab berdasarkan fakta Nafiz—salah atau tidak tersedia dalam skenario yang realistis.
- **Medium**: dampaknya material tetapi terbatas pada jenis input, entity, session, atau failure mode tertentu dan masih relatif mudah dipulihkan.
- **Low**: edge case, misleading diagnostic, atau penurunan kualitas yang tidak langsung merusak knowledge utama.

## Metodologi dan Batasan

Audit dilakukan melalui:

1. Static review seluruh jalur backend yang berhubungan dengan chat dan memory:
   - `routes/chat_routes.py`
   - `services/llm_service.py`
   - `services/memory_service.py`
   - `services/qdrant_service.py`
   - `services/neo4j_service.py`
   - model, schema, config, migration, startup task, dan regression test terkait.
2. Read-only inspection terhadap backend yang sedang berjalan melalui endpoint graph, memory jobs, system stats, history, dan logs.
3. Cross-check terhadap dokumen audit lama agar issue yang sudah diperbaiki tidak dilaporkan ulang sebagai issue aktif.

Audit ini tidak mengirim prompt pengujian ke API LLM eksternal dan tidak melakukan stochastic evaluation terhadap model. Regression test tidak dapat dieksekusi dari shell audit karena virtualenv menunjuk executable Python lama yang sudah tidak tersedia; Python global juga tidak memiliki dependency backend. Isi regression test tetap direview secara statis. Keterbatasan ini tidak dijadikan issue AI/KG.

Snapshot data lokal saat audit:

- 32 nodes dan 38 facts di graph.
- Seluruh 38 facts memiliki `fact_id` dan provenance.
- 38 facts berstatus aktif; belum ada fact inactive.
- 12 memory jobs berstatus `completed`; tidak ada job failed/pending pada snapshot.
- Tidak ditemukan duplicate `(label, name)` atau Person unresolved tanpa `identity_context` pada snapshot.
- Ditemukan 8 fact aktif yang bersifat sementara: 5 `WANTS`, 2 `DISCUSSING`, dan 1 `DOING`.
- Ditemukan 1 konflik fact aktif pada relation yang secara alami bernilai tunggal.

---

## Critical

**Tidak ada temuan Critical.**

Alasan utama:

- SQLite tetap menjadi sumber raw conversation yang dapat dipakai untuk recovery/re-extraction.
- Outbox menyimpan payload extraction secara durable dan retry per tahap.
- Fact graph dapat dinonaktifkan/dihapus dan node dapat dikoreksi melalui API granular.
- Penghapusan session sudah menghapus provenance yang hanya didukung session tersebut.
- Collision nama global, deterministic Qdrant overwrite, dan extraction pronoun tanpa context yang pernah menjadi Critical pada versi lama sudah diperbaiki.

---

## High

### H1. Fakta sementara diperlakukan sebagai keadaan aktif tanpa batas waktu

**Bukti kode:**

- `services/llm_service.py:358-417` meminta extractor mengambil fakta secara exhaustive dan menyediakan relation seperti `FEELS`, `WANTS`, `DOING`, `PLANNING`, dan `DISCUSSING`.
- `services/neo4j_service.py:207-238` selalu mengatur setiap edge hasil extraction menjadi `is_current = true`.
- `services/neo4j_service.py:816-851` melindungi node yang mempunyai fact aktif dari proses forgetting. Tidak ada TTL, `valid_until`, event time, atau lifecycle policy per relation.

**Bukti runtime:** terdapat 8 fact sementara yang masih aktif: 5 `WANTS`, 2 `DISCUSSING`, dan 1 `DOING`. Seluruh 38 fact di graph masih current.

**Masalah:** kalimat seperti “aku lagi capek”, “aku sedang mengerjakan X”, atau “aku mau menonton Y” bukan fakta identitas permanen. Saat ini semuanya masuk graph sebagai keadaan aktif dan dapat terus diberikan kepada Claire berminggu-minggu atau berbulan-bulan kemudian.

**Dampak:** Claire dapat menjawab berdasarkan keadaan yang sudah kedaluwarsa, misalnya menganggap Nafiz masih mengerjakan, menginginkan, membahas, atau merasakan sesuatu yang hanya benar pada satu waktu. Ini merusak kualitas utama personal assistant: memahami keadaan Nafiz saat ini.

**Rekomendasi:**

- Pisahkan `Fact`, `State`, dan `Event`.
- Tambahkan `observed_at`, `valid_from`, `valid_until`, serta lifecycle policy per relation.
- Relation transient seperti `FEELS`, `DISCUSSING`, dan sebagian `WANTS/DOING` harus mempunyai TTL atau otomatis menjadi historical event.
- Retrieval default hanya boleh memasukkan state current yang belum expired; event lama hanya diambil bila user menanyakan histori.

### H2. Graph menerima contradiction pada relation single-valued tanpa guard

**Bukti kode:**

- `services/llm_service.py:289-322` hanya melakukan sanitasi bentuk dasar dan pronoun.
- `services/neo4j_service.py:172-296` menerima setiap edge valid secara referensial lalu melakukan `MERGE`; tidak ada cardinality map atau validasi bahwa satu source hanya boleh memiliki satu target aktif untuk relation tertentu.

**Bukti runtime:** satu pesan user yang membedakan “asal Kediri” dari “lahir di Malang” menghasilkan dua edge aktif untuk Person yang sama:

```text
Person -[BORN_IN]-> kediri   (current=true)
Person -[BORN_IN]-> malang   (current=true)
```

Kedua fact berasal dari source message yang sama. Extractor salah memetakan “asal Kediri” menjadi `BORN_IN`, lalu backend menerima kedua hasil sebagai kebenaran aktif.

**Masalah:** relation seperti `BORN_IN`, `BORN_ON`, dan banyak atribut identitas bersifat single-valued. Prompt saja tidak cukup untuk menjamin model memilih semantics dan cardinality yang benar.

**Dampak:** Claire menerima dua jawaban yang saling bertentangan untuk pertanyaan sederhana. Ranking mungkin memilih salah satunya tanpa memberi tahu bahwa graph ambigu.

**Rekomendasi:**

- Definisikan relation registry dengan cardinality, subject/target type, mutability, dan temporal semantics.
- Validasi seluruh batch extraction sebelum ada write.
- Untuk relation single-valued, tolak atau quarantine batch yang memberi lebih dari satu target aktif tanpa explicit correction.
- Bedakan “asal dari” dengan “lahir di”, misalnya `ORIGINATES_FROM` dan `BORN_IN`.
- Tambahkan status `pending_review` untuk konflik, jangan langsung `current=true`.

### H3. Jawaban Claire sendiri disimpan dan dipresentasikan kembali sebagai fakta dari Nafiz

**Bukti kode:**

- `services/memory_service.py:271-278` menyimpan satu string gabungan: `User: ...\nClaire: ...` ke Qdrant.
- `services/qdrant_service.py:94-109` mengembalikan string tersebut tanpa struktur role atau trust level.
- `services/llm_service.py:158-169` memasukkannya ke `<past_conversations>` dan menyatakan bahwa fakta dalam `<long_term_facts>` **dan** `<past_conversations>` berasal dari informasi yang sebelumnya diberikan Nafiz.

**Masalah:** pernyataan terakhir tidak benar untuk separuh isi Qdrant. Teks `Claire:` berasal dari model, bukan dari Nafiz. Jika Claire pernah berhalusinasi, salah menyimpulkan, atau memberi detail spekulatif, detail itu disimpan permanen dalam vector memory dan pada retrieval berikutnya diberi status seolah user-grounded.

**Dampak:** tercipta self-reinforcing hallucination loop:

```text
Claire salah menjawab
  -> jawaban salah masuk Qdrant
  -> Qdrant mengambilnya pada turn lain
  -> prompt menyebutnya sebagai informasi dari Nafiz
  -> Claire makin yakin pada informasi yang salah
```

Knowledge Graph memang hanya diekstrak dari user message, sehingga graph tidak langsung tercemar oleh jawaban Claire. Namun response generation tetap dapat salah karena vector context memiliki trust yang keliru.

**Rekomendasi:**

- Simpan user dan assistant content sebagai field terpisah dengan `source_role` dan `epistemic_status`.
- Untuk factual long-term retrieval, embed dan kembalikan hanya user assertion atau summary yang secara eksplisit diturunkan dari user message.
- Assistant response boleh disimpan untuk conversational recall, tetapi prompt harus menyebutnya sebagai historical model output yang tidak boleh dipakai sebagai bukti fakta.
- Idealnya Qdrant menyimpan reference ke message IDs; prompt builder memilih potongan source yang sesuai, bukan raw gabungan Q+A.

### H4. Kedua memory store digate oleh satu router LLM Gemini yang fail-closed

**Bukti kode:**

- `services/memory_service.py:76-90` memanggil router, lalu langsung mengembalikan context kosong bila keyword kosong. Qdrant dan Neo4j sama-sama tidak dicari.
- `services/llm_service.py:461-509` memakai provider Google secara hardcoded dan mengubah semua error/JSON failure menjadi `[]`.
- `services/memory_service.py:32-61` hanya menyediakan deterministic hints untuk sebagian kecil domain: relationship, pekerjaan, kelahiran, pendidikan, dan tempat tinggal.
- `configs/settings.py:9-12` mewajibkan `GEMINI_API_KEY` dari environment meskipun chat utama dapat memilih Groq, OpenAI, atau Hugging Face.

**Masalah:** router bukan hanya mengoptimalkan pencarian; router menjadi sakelar hidup-mati seluruh long-term memory. Salah klasifikasi satu turn, output JSON yang malformed, API Gemini timeout, quota habis, atau key bermasalah semuanya terlihat sama: tidak ada memory.

Jika chat memakai provider lain dan provider itu sehat, Claire tetap dapat menjawab—tetapi menjadi amnesia karena fungsi router/extractor diam-diam tetap bergantung pada Gemini.

**Dampak:** pertanyaan memory di luar rule deterministik, misalnya preferensi, alergi, nama orang, film, keputusan, atau masalah lama, dapat dijawab seolah Claire tidak pernah diberi tahu. Tidak ada sinyal ke response generator bahwa retrieval gagal; context kosong tampak sama dengan “memang tidak ada fakta”.

**Rekomendasi:**

- Bedakan hasil router `not_needed`, `needed`, dan `router_failed`.
- Pada `router_failed`, tetap jalankan semantic search dan deterministic lexical/entity fallback.
- Explicit recall phrase seperti “ingat”, “pernah bilang”, “favoritku”, atau “siapa X” harus dapat memaksa retrieval tanpa bergantung penuh pada LLM router.
- Jadikan provider/model memory pipeline configurable dan punya fallback, tidak hardcoded Google.
- Jangan mewajibkan Gemini `.env` bila key database atau provider lain dapat menjadi memory model.

### H5. Kegagalan Neo4j pada retrieval dapat menggagalkan seluruh jawaban Claire

**Bukti kode:**

- `services/neo4j_service.py:12-47` mencatat connectivity failure saat startup tetapi tidak menandai service unavailable atau menghentikan startup.
- `services/memory_service.py:92-101` mengambil hasil Qdrant dan Neo4j melalui `future.result()` tanpa isolasi error per store.
- `services/qdrant_service.py:98-112` menangani error search dengan mengembalikan list kosong, sedangkan `Neo4jService.search_knowledge()` tidak mempunyai fallback setara.
- `routes/chat_routes.py:158-213` menangkap error tersebut pada stream sebagai generic/upstream error walaupun LLM belum tentu pernah dipanggil.

**Masalah:** Neo4j adalah sumber konteks tambahan, tetapi kegagalannya menjadi fatal bagi chat yang membutuhkan memory. Backend dapat terlihat sehat setelah startup connectivity failure, lalu baru gagal ketika user mengirim pertanyaan yang memicu retrieval.

**Dampak:** bila service Neo4j lokal berhenti, database terkunci, atau query gagal, Claire tidak sekadar menjawab tanpa graph—ia dapat gagal menjawab sama sekali. Error SSE juga misleading karena diklasifikasikan seperti kegagalan provider LLM.

**Rekomendasi:**

- Isolasi retrieval per store dan kembalikan partial context bila salah satu gagal.
- Sertakan status internal `qdrant_available`, `neo4j_available`, dan `router_available` tanpa mengekspose detail teknis ke persona response.
- Bedakan `MEMORY_BACKEND_ERROR` dari `UPSTREAM_LLM_ERROR` untuk diagnosis frontend/log.
- Sediakan strict startup mode dan degraded mode yang eksplisit.

---

## Medium

### M1. LLM dapat menonaktifkan fact lama dengan scope lebih luas dari contradiction yang dibuktikan

**Bukti kode:** `services/neo4j_service.py:252-296`.

`supersedes` hanya dibatasi agar fact lama mempunyai source entity yang sama. Tidak ada validasi bahwa relation lama sama atau memang bertentangan dengan relation baru. Sebuah fact `WORKS_AT` baru secara teoritis dapat menonaktifkan fact `DATING` lama bila extractor memilih `fact_id` yang salah tetapi source-nya sama-sama Nafiz.

Selain itu, `replaces_current_relation=true` menonaktifkan semua target aktif untuk source+relation. Ini berbahaya bagi relation multi-valued seperti `WORKS_AT`, `LIKES`, `SKILLED_AT`, atau `HAS_FAMILY`.

Fact lama tidak dihapus secara fisik dan dapat diaktifkan kembali, sehingga issue ini Medium, bukan High/Critical.

**Rekomendasi:** validasi supersession terhadap relation registry; wajibkan relation sama untuk replacement biasa; gunakan explicit fact IDs untuk relation multi-valued; quarantine invalidation berisiko.

### M2. Mention Person tanpa identity context selalu membuat entity baru

**Bukti kode:** `services/neo4j_service.py:83-102`.

Untuk Person selain Nafiz dan Claire, `identity_context` kosong menghasilkan `person:unresolved:<uuid4>`. Ini mencegah homonym collision, tetapi dua penyebutan orang yang sama pada pesan berbeda dapat menghasilkan dua nodes yang tidak pernah terhubung.

Snapshot sekarang tidak memiliki unresolved Person, jadi ini belum terbukti merusak data aktif. Risiko muncul saat extractor tidak mendapat pembeda yang eksplisit.

**Rekomendasi:** gunakan session-scoped entity focus dan candidate resolution; tautkan ulang hanya dengan bukti eksplisit; jangan membuat Person permanen bila identity minimum belum cukup.

### M3. Heuristik “recall question” dapat membuang assertion baru yang berbentuk pertanyaan

**Bukti kode:** `services/llm_service.py:272-286` dan pemakaiannya pada `services/llm_service.py:344-356`.

Pesan langsung dilewati dari extraction jika dimulai dengan `apa`, `apakah`, `siapa`, `kapan`, dan beberapa kata tanya lain, atau mengandung pola “kamu ingat/tahu”. Heuristik tidak membedakan pure recall dari pertanyaan yang juga menyatakan fakta baru.

Contoh yang berpotensi tidak pernah masuk graph:

```text
“Apa kamu tahu aku sekarang kerja di Gojek?”
“Kamu masih ingat aku sekarang tinggal di Bandung kan?”
```

Keduanya mengandung assertion eksplisit, tetapi dapat dianggap recall-only sebelum extractor dipanggil.

**Rekomendasi:** ubah classifier menjadi tiga kelas (`pure_question`, `mixed_assertion`, `assertion`) dan hanya skip kelas pertama; tambahkan regression corpus bahasa Indonesia informal.

### M4. Qdrant selalu memberikan top-k walaupun similarity rendah

**Bukti kode:** `services/qdrant_service.py:94-109`.

`query_points(..., limit=3)` tidak memakai score threshold dan score tidak dikembalikan ke caller. Begitu router membuka retrieval, tiga nearest memories selalu dianggap layak walaupun tidak ada memory yang benar-benar relevan.

**Dampak:** prompt dapat menerima percakapan lama yang tidak berhubungan, lalu mengalihkan jawaban atau memperkuat detail yang salah. Guard system prompt membantu, tetapi bukan quality gate deterministik.

**Rekomendasi:** kembalikan score+metadata, evaluasi threshold dengan dataset percakapan Nafiz, lalu terapkan threshold/reranking gabungan semantic score, keyword overlap, recency, dan source trust.

### M5. Embedding layer dapat diam-diam tidak cocok atau tidak sehat

**Bukti kode:** `services/qdrant_service.py:20-26` dan `services/qdrant_service.py:46-50`.

Project memakai `all-MiniLM-L6-v2`, sementara percakapan Claire dominan bahasa Indonesia informal. [Model card resminya](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) menjelaskan base model uncased dan daftar training corpus yang dominan English-centric, tanpa bukti evaluasi khusus bahasa Indonesia atau slang Indonesia. Kecocokannya untuk corpus project ini karena itu belum terjamin. Selain itu, bila encoder gagal dimuat, `embed_text()` mengembalikan zero vector dan pipeline tetap terlihat berjalan.

Snapshot logs saat audit tidak menunjukkan encoder load failure, sehingga fallback zero-vector belum terbukti terjadi sekarang. Namun bila terjadi, memory dapat disimpan dengan vector tidak bermakna atau search menjadi kosong/acak tanpa health signal yang tegas.

**Rekomendasi:** gunakan embedding multilingual yang dievaluasi pada data Indonesia personal, fail closed untuk write zero-vector, dan tampilkan health state/dimension/model version pada stats.

### M6. Extraction hanya melihat empat message sebelumnya

**Bukti kode:**

- `routes/chat_routes.py:123-125` dan `routes/chat_routes.py:192-193` memotong history ke empat message.
- `services/memory_service.py:487` kembali memotong ke empat message.
- `services/llm_service.py:325-341` membatasi formatter ke empat message.

Jika subject disebut lebih awal lalu Nafiz menjawab secara eliptis seperti “iya, dia mulai bulan depan”, extractor tidak dapat meresolve `dia`. Pronoun guard mencegah node sampah, tetapi fakta yang valid akan hilang dari graph secara diam-diam.

**Rekomendasi:** simpan active entities/session state atau summary faktual per session; gunakan retrieval khusus history untuk pronoun resolution; tetap jangan menebak bila ambiguity tersisa.

### M7. Short-term conversation context dipotong 30 message tanpa summary aktif

**Bukti kode:** `services/memory_service.py:104-117`; field `Conversation.summary` ada tetapi tidak pernah diisi atau dipakai pada prompt.

Setelah kira-kira 15 turn user-assistant, bagian awal session tidak lagi dikirim ke model. Long-term retrieval tidak menjamin semua instruksi, keputusan brainstorming, atau state percakapan awal berhasil diekstrak dan dipanggil kembali.

Ini bukan issue performa: dampaknya adalah continuity correctness. Claire dapat lupa constraint atau keputusan yang masih berlaku dalam session panjang.

**Rekomendasi:** buat rolling session summary yang memisahkan keputusan, unresolved questions, dan temporary working context; jangan campur summary session dengan long-term fact tanpa provenance.

### M8. Delimiter memory tidak di-escape sehingga isi tersimpan dapat keluar dari boundary

**Bukti kode:** `services/llm_service.py:158-169` dan `services/llm_service.py:419-425`.

Raw memory dimasukkan melalui concatenation ke tag XML. Isi tidak meng-escape string seperti `</past_conversations>` atau `</existing_knowledge>`. Karena Nafiz adalah developer, teks yang di-paste dapat secara sah berisi prompt, XML, atau contoh instruksi—tanpa niat menyerang sistem.

Pada retrieval berikutnya, isi itu dapat menutup tag lebih awal dan mengubah cara model memahami batas antara data pasif dan instruksi. Konteks local/single-user menurunkan severity dari sisi security, tetapi risiko salah interpretasi tetap material.

**Rekomendasi:** gunakan serialization aman (misalnya JSON string terstruktur), escape delimiter, sertakan source role, dan jangan mengandalkan tag+instruksi natural-language sebagai satu-satunya isolation boundary.

---

## Low

### L1. Invalid relation output dapat membuat outbox mengulang payload yang sama tanpa akhir

**Bukti kode:**

- `services/llm_service.py:289-322` tidak memvalidasi schema/relation secara strict.
- `services/neo4j_service.py:177-180` membersihkan karakter relation tetapi tidak memastikan identifier hasilnya selalu valid untuk seluruh kemungkinan output.
- `services/memory_service.py:288-324` menyimpan extraction sebagai completed sebelum graph merge; retry berikutnya memakai payload extraction yang sama.
- `services/memory_service.py:329-369` tidak memiliki maximum attempts/dead-letter state.

Payload deterministik yang tidak dapat ditulis dapat retry selamanya. Dampaknya terbatas pada satu memory job dan terlihat melalui endpoint jobs, sehingga severity Low.

**Rekomendasi:** strict schema sebelum menandai extraction complete, maximum attempts, status `dead_letter`, dan opsi re-extract setelah model/prompt diperbaiki.

### L2. Prompt melarang kata teknis terlalu luas

**Bukti kode:** `services/llm_service.py:136-137`.

Claire dilarang **pernah** menyebut `Neo4j`, `Qdrant`, `Database`, atau `System`. Tujuannya menyembunyikan implementasi memory, tetapi larangannya global. Saat Nafiz bertanya soal database atau system design sebagai topik teknis, instruksi ini dapat mengurangi kualitas jawaban atau membuat istilah yang tepat dihindari.

**Rekomendasi:** larang pengungkapan mekanisme internal hanya ketika Claire membahas cara ia mengingat, bukan ketika istilah tersebut adalah subject pertanyaan user.

### L3. Endpoint chat non-stream menerima session ID yang tidak ada

**Bukti kode:** `routes/chat_routes.py:86-104`.

Jalur non-stream hanya memperbarui conversation jika ditemukan, tetapi tidak memberi 404 bila session ID invalid. Ia tetap menghasilkan jawaban dan menjadwalkan penyimpanan dengan ID tersebut. Jalur stream sudah memvalidasi session pada `routes/chat_routes.py:63-69`.

Dengan konfigurasi SQLite saat ini tidak terlihat ada `PRAGMA foreign_keys=ON`, sehingga ada risiko ghost messages; memory job kemudian dibatalkan karena conversation tidak ada.

**Rekomendasi:** samakan validation contract non-stream dengan stream dan aktifkan SQLite foreign-key enforcement.

### L4. Kegagalan consolidation dapat dicatat seolah jadwal berhasil

**Bukti kode:**

- `services/neo4j_service.py:809-857` menangkap exception dan tetap mengembalikan stats.
- `main.py:39-51` tetap memperbarui `last_consolidation_time` setelah pemanggilan tersebut.

Maintenance yang gagal tidak dicoba lagi sampai interval harian berikutnya. Saat ini current facts dilindungi dari forgetting, jadi dampak langsung ke correctness kecil.

**Rekomendasi:** propagate status gagal atau return field `success`; update waktu terakhir hanya setelah transaction berhasil.

---

## Urutan Perbaikan yang Disarankan

### Prioritas 0 — lindungi kebenaran graph

1. Tambahkan relation registry dan batch validator untuk cardinality/semantics.
2. Koreksi conflict `BORN_IN` yang sudah ada setelah memastikan fakta yang benar dari source message.
3. Pisahkan state/event/fact dan beri expiry pada relation transient.
4. Hentikan penggunaan assistant output sebagai user-grounded evidence di Qdrant.

### Prioritas 1 — hilangkan silent amnesia dan total chat failure

1. Ubah router menjadi tri-state dan sediakan fallback deterministic/semantic.
2. Lepaskan hard dependency memory pipeline dari satu provider Gemini.
3. Isolasi error Qdrant/Neo4j; izinkan partial context dan beri diagnostic code yang benar.

### Prioritas 2 — perkuat extraction dan retrieval

1. Terapkan strict Pydantic schema untuk node/edge extraction.
2. Batasi scope supersession berdasarkan cardinality dan relation type.
3. Tambahkan confidence/review state untuk fact ambigu.
4. Evaluasi embedding multilingual dan threshold menggunakan corpus Indonesia milik project.
5. Tambahkan session entity state dan rolling summary.

### Prioritas 3 — rapikan edge cases

1. Escape/structure memory payload sebelum masuk prompt.
2. Tambahkan dead-letter/re-extraction untuk poison outbox job.
3. Samakan validasi session stream dan non-stream.
4. Persempit larangan vocabulary pada persona prompt.

## Regression Test yang Paling Bernilai

Tambahkan test berikut sebelum menyebut memory pipeline bulletproof:

1. **Single-valued contradiction test**: satu extraction batch tidak boleh menghasilkan dua `BORN_IN` current untuk source yang sama.
2. **Origin vs birthplace test**: “asal Kediri, lahir di Malang” harus menghasilkan relation berbeda.
3. **Transient expiry test**: `FEELS`, `DISCUSSING`, dan temporary `DOING` tidak boleh tetap current tanpa batas.
4. **Self-grounding test**: detail yang hanya muncul pada assistant response tidak boleh dipresentasikan sebagai user assertion pada turn berikutnya.
5. **Router outage test**: Gemini/router failure tidak boleh mematikan Qdrant+Neo4j retrieval fallback.
6. **Neo4j outage test**: chat tetap menghasilkan response dengan degraded memory ketika graph unavailable.
7. **Mixed question/assertion test**: “kamu ingat aku sekarang kerja di X?” tetap menulis assertion baru.
8. **Indonesian retrieval evaluation**: corpus minimal 50-100 query dengan slang, alias, typo, dan code-switching; ukur precision@3 dan recall fact.
9. **Long-session continuity test**: constraint dari awal session tetap tersedia setelah lebih dari 30 messages melalui summary/session state.
10. **Prompt-boundary test**: memory yang mengandung closing tag atau contoh system prompt tetap diperlakukan sebagai data.

## Hal yang Sudah Kuat

Beberapa fondasi saat ini sudah baik dan tidak seharusnya dirombak tanpa alasan:

- Entity identity tidak lagi memakai global unique name.
- Person bernama sama dapat dibedakan menggunakan `identity_context`.
- Generic pronoun entity diblokir.
- Qdrant memakai event ID, sehingga repeated message tidak saling overwrite.
- SQLite + outbox menjaga raw turn sebelum vector/graph processing.
- Vector, extraction, dan graph stage memiliki status retry terpisah.
- Fact mempunyai `fact_id`, `is_current`, timestamp, dan provenance.
- Graph retrieval hanya mengambil fact current dan mempunyai lexical/importance/recency ordering.
- Session deletion membersihkan provenance dan hanya menghapus fact tanpa source lain.
- Node dan fact dapat dikoreksi secara granular.
- Snapshot runtime menunjukkan seluruh 12 outbox jobs completed dan tidak ada provenance yang hilang.

## Kesimpulan Akhir

Claire saat ini sudah jauh lebih aman daripada versi yang dijelaskan di audit lama, khususnya terhadap overwrite, homonym collision, partial write, dan deletion provenance. Tidak ada alasan yang cukup untuk memberi label Critical.

Risiko terbesar sekarang bukan durability, melainkan **epistemic correctness**: backend belum membedakan fakta permanen, state sementara, event historis, ucapan user, dan jawaban model dengan cukup ketat. Selama kelima issue High belum diperbaiki, Claire dapat terlihat memiliki memory yang kuat tetapi tetap yakin pada state basi, contradiction, atau hasil grounding dari ucapannya sendiri.
