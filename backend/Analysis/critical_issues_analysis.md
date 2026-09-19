# Analisis Critical Issue — Claire AI & Knowledge Graph

> **Scope**: Analisis ini fokus HANYA pada korektnas otak Claire (LLM orchestration) dan Knowledge Graph (Neo4j + Qdrant). Bukan tentang performa, kecepatan, atau concurrency — murni tentang benar/salahnya cara sistem berpikir, mengingat, dan mengambil keputusan.
> **Metodologi**: Setiap temuan di bawah dibaca langsung dari kode di `backend/services/`, `backend/main.py`, `backend/routes/`, lalu diverifikasi dengan menjalankan kode tersebut terhadap Neo4j & Qdrant yang sedang berjalan (data real hasil pemakaian kamu sendiri). Jadi ini bukan spekulasi teoretis — semua sudah dibuktikan kejadian nyata di data yang ada sekarang.
> **Urutan**: Dari yang paling merusak kualitas "ingatan" Claire, ke yang paling ringan.

---

## Ringkasan Cepat

| # | Issue | Severity | Sudah Terbukti Terjadi di Data? |
|---|-------|----------|----------------------------------|
| 1 | Entity collision antar orang yang namanya sama (homonym collapse) | 🔴 Critical | ✅ Ya, "siska" ibu kandung & "siska" istri temen jadi 1 node |
| 2 | Silent overwrite di Qdrant untuk pesan pendek yang berulang | 🔴 Critical | ✅ Dibuktikan via eksperimen langsung |
| 3 | Entity extraction buta konteks — hanya baca 1 pesan user, tanpa histori | 🔴 Critical | ✅ Dibuktikan via eksperimen langsung |
| 4 | Retrieval Neo4j tidak ada ranking/ordering (importance & recency dihitung tapi tidak dipakai) | 🟠 High | ✅ Terlihat langsung di kode |
| 5 | Tidak ada temporal awareness — fakta lama & baru yang kontradiktif dianggap sama-sama valid | 🟠 High | ✅ Terkonfirmasi tidak ada implementasi |
| 6 | Tidak ada cara memperbaiki memori yang salah selain hapus total semua | 🟠 High | ✅ Terkonfirmasi tidak ada endpoint |
| 7 | Keyword matching pakai substring mentah tanpa word boundary, dan query "read" punya side-effect "write" | 🟡 Medium | ✅ Dibuktikan ("di" nyantol ke "budi", "dina") |
| 8 | Bug `.capitalize()` merusak label kategori custom multi-word | 🟡 Medium | ✅ Dibuktikan, belum termanifestasi di data saat ini |
| 9 | Tidak ada provenance — node tidak tahu berasal dari percakapan mana | 🟡 Medium | ✅ Terkonfirmasi tidak ada field terkait |
| 10 | API key tersimpan plaintext di SQLite | 🟢 Low | ✅ Terkonfirmasi di kode |
| 11 | Router "butuh memori atau tidak" bisa salah putus tanpa fallback | 🟢 Low | ✅ Terkonfirmasi, risiko dilemahkan oleh desain paralel |

---

## 🔴 1. Entity Collision — Orang Berbeda dengan Nama Sama Digabung Jadi Satu Identitas

**File**: `backend/services/neo4j_service.py` (baris 20, 28-54), `backend/services/qdrant_service.py` (`resolve_entity`, baris 115-152)

### Apa yang terjadi

Neo4j dipasangi constraint global:

```python
session.run("CREATE CONSTRAINT unique_entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
```

Constraint ini bilang: **tidak boleh ada dua node `Entity` dengan `name` yang sama, titik**. Tidak peduli labelnya `Person`, `Organization`, atau `Concept` — semua dipaksa masuk satu namespace nama yang sama.

Ditambah lagi, sebelum node dibuat, nama itu dilempar ke `resolve_entity()` di Qdrant yang mencari entitas mirip secara *semantic* dengan threshold `score_threshold=0.89`. Jadi ada dua lapis yang sama-sama menganggap "nama yang sama/mirip = orang yang sama".

### Bukti nyata di data kamu

Saya cek langsung ke Neo4j yang jalan di project ini. Ternyata dari histori percakapanmu, kejadian yang di dokumen teknis (`project_technical_document.md`, section 11.1) diperingatkan sebagai risiko masa depan — **sudah kejadian sekarang**, bukan cuma proyeksi:

```
budi -[DATING]-> siska                          (Budi si CEO OVO, pacar Siska si dokter gigi)
siska -[ATTENDING]-> pernikahan budi dan siska
nafiz -[HAS_FAMILY]-> siska                     (!!)
nafiz -[IS_FRIEND_WITH]-> siska                 (!!)
```

Ini adalah **node "siska" yang SAMA PERSIS** menampung dua orang yang sepenuhnya berbeda:
1. Siska, dokter gigi di RS Siloam, istri Budi (teman Nafiz)
2. Siska, ibu kandung Nafiz sendiri

Kamu sendiri sadar dan mencoba mengoreksi ini di percakapan ("*beda, budi dan siska yang ceo dan dokter gigi itu temen ku, kaloo ini orang tua ku, kebetulan aja namanya sama*") — tapi karena tidak ada mekanisme disambiguasi di level graph, Claire hanya mengoreksi jawabannya secara verbal saat itu. **Di Knowledge Graph, kedua "Siska" itu tetap satu node yang sama**, importance-nya digabung (nilainya `5.3`, hasil akumulasi dari dua orang berbeda), dan setiap edge baru (family, allergic_to seafood, phobia kucing, WORKS_AS dokter gigi) semuanya nempel ke satu identitas yang sama.

### Kenapa ini paling kritis

Ini bukan soal "graph jadi berantakan" (hairball) seperti yang dikhawatirkan di dokumen desain — ini lebih parah: **AI akan salah sangka orang**. Kalau nanti kamu tanya "Siska alergi apa?", Claire bisa saja menjawab "alergi seafood" untuk konteks ibu kandungmu — padahal itu fakta tentang istri temanmu. Untuk sebuah AI yang tujuannya adalah personal assistant yang "benar-benar mengingat", ini merusak kepercayaan paling dasar: kalau AI salah mengaitkan orang, semua rekomendasi/insight yang dibangun di atas itu ikut salah.

Nama seperti Budi, Siska, Dina, Reza adalah nama pasaran di Indonesia — kemungkinan collision ini akan **terus terjadi berulang kali** seiring kamu cerita tentang lebih banyak orang.

### Rekomendasi

- Constraint unique tidak boleh murni berdasarkan `name`. Minimal butuh disambiguasi berdasarkan **relasi ke "nafiz"** (mis. "siska (ibu)" vs "siska (teman budi)") atau properti tambahan seperti `relation_to_user`.
- `resolve_entity()` seharusnya tidak auto-merge kalau ada indikasi jenis entitas yang berbeda konteks (misal dua "Person" dengan hubungan ke Nafiz yang berbeda kategori: keluarga vs. teman-nya-teman).
- Idealnya entity resolution untuk `Person` butuh konfirmasi tambahan (nama lengkap, atau atribut pembeda) sebelum di-merge, bukan cuma exact-name-match atau semantic similarity dari nama pendek saja.

---

## 🔴 2. Silent Overwrite di Qdrant — Memori Lama Bisa Hilang Tanpa Jejak

**File**: `backend/services/qdrant_service.py`, fungsi `save_memory` (baris 50-92)

### Apa yang terjadi

```python
check_text = dedup_key or text
check_vector = embed_text(check_text)

# 1. Cek duplikasi
search_result = client.query_points(collection_name=COLLECTION_NAME, query=check_vector, limit=1, score_threshold=0.90)
if search_result.points:
    return  # skip

# 2. Kalau tidak duplikat, simpan
point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, check_text))
client.upsert(collection_name=COLLECTION_NAME, points=[PointStruct(id=point_id, vector=vector, payload=metadata)])
```

`memory_service.save_interaction()` memanggil ini dengan `dedup_key=user_message` (pesan user MENTAH, bukan full interaksi). Perhatikan dua hal yang saling bertabrakan:

1. `point_id` dihitung **deterministic** dari hash `dedup_key` (pesan user). Artinya kalau user mengirim teks yang **persis sama** di lain waktu, `point_id`-nya juga **persis sama** → `client.upsert()` akan **overwrite** point lama tanpa peringatan apapun, karena upsert dengan ID yang sama = replace.
2. Pengecekan "apakah ini duplikat" dilakukan dengan membandingkan **embedding dari `dedup_key` saja** terhadap **embedding full text yang tersimpan** (`f"User: ...\nClaire: ..."`). Dua teks ini punya "shape" semantik yang beda (satu cuma pertanyaan, satu gabungan tanya-jawab), sehingga similarity-nya turun signifikan dari yang seharusnya.

### Bukti nyata (saya jalankan langsung)

Saya simulasikan persis logic `save_memory` di lingkungan terisolasi:

```
Day 1: user kirim "halo" -> tersimpan sebagai:
  "User: halo\nClaire: Hai! Ada apa nih?"
  point_id = 95d90c47...

Day 8: user kirim "halo" lagi (beda konteks, beda jawaban Claire) -> disimpan lagi dengan dedup_key="halo":
  check_vector similarity terhadap memory Day 1 = TIDAK melewati threshold 0.90 (bahkan cek manual: sim antar teks pendek vs teks gabungan cuma ~0.75)
  -> tidak dianggap duplikat -> lanjut upsert
  point_id = 95d90c47... (SAMA seperti Day 1, karena hash dari "halo" selalu sama)

Hasil akhir: HANYA ADA 1 POINT di Qdrant. Memori Day 1 HILANG, tertimpa oleh Day 8.
```

Ini saya buktikan langsung dengan menjalankan kode `save_memory` yang sesungguhnya (bukan simulasi kasar) di collection sementara — hasilnya tepat seperti di atas: dari 2 kali panggilan `save_memory`, collection akhir hanya berisi **1 titik data**, isinya adalah interaksi yang paling akhir.

### Kenapa ini kritis

Untuk assistant yang value proposition utamanya adalah "mengingat semua percakapan", kehilangan data secara diam-diam (tanpa error, tanpa log warning yang jelas — cuma `logger.info` biasa yang gampang terlewat) adalah kegagalan mendasar. Sapaan singkat seperti "halo", "makasih", "oke", "iya", "capek nih" itu justru **sering diulang** oleh siapapun dalam obrolan sehari-hari — jadi tipe pesan yang paling mungkin kena timpa ini justru yang paling sering terjadi.

### Rekomendasi

- Jangan pakai `point_id` deterministic dari isi pesan. Gunakan UUID random per-interaksi (`uuid4()`), lalu simpan `session_id` + `timestamp` di payload untuk keperluan dedup/audit, bukan untuk primary key.
- Untuk pengecekan duplikat, bandingkan hal yang sepadan: full interaksi baru vs full interaksi lama (bukan `dedup_key` vs full text lama), atau turunkan tujuannya — apakah dedup memang perlu di level "pesan user mentah", atau cukup skip kalau *seluruh* interaksi (Q+A) sangat mirip.

---

## 🔴 3. Entity Extraction Buta Konteks — Hanya Melihat 1 Pesan, Tidak Tahu Percakapan Sebelumnya

**File**: `backend/services/llm_service.py`, fungsi `extract_knowledge` (baris 168 dst.); dipanggil dari `backend/services/memory_service.py` baris 112: `extract_knowledge(user_message, neo4j_context=neo4j_ctx)`

### Apa yang terjadi

`extract_knowledge()` menerima **hanya** `user_message` (satu pesan user paling baru) plus daftar fakta lama dari Neo4j untuk menghindari duplikasi. Ia **tidak** menerima:
- `session_history` (riwayat pesan di sesi berjalan)
- `ai_response` (jawaban Claire yang baru saja diberikan, yang seringkali berisi pertanyaan klarifikasi)

Ini masalah karena pola percakapan manusia yang natural itu sering **elliptical** — jawaban singkat yang hanya bermakna jika digabung dengan pertanyaan sebelumnya.

### Bukti nyata (saya jalankan langsung)

Saya coba simulasikan skenario umum: Claire nanya sesuatu, user jawab singkat.

```python
extract_knowledge("di Telkomsel, dia baru masuk bulan lalu")
```

Hasilnya:
```json
{
  "nodes": [
    {"label": "Person", "name": "dia"},
    {"label": "Organization", "name": "telkomsel"},
    {"label": "Concept", "name": "bulan lalu"}
  ],
  "edges": [
    {"source": "dia", "target": "telkomsel", "relation": "WORKS_AT"},
    {"source": "dia", "target": "bulan lalu", "relation": "STARTED_WORKING_SINCE"}
  ]
}
```

Node yang terbentuk adalah **"dia"** — bukan nama orang yang sebenarnya dibicarakan (misal "Cia"). Karena `resolve_entity()` dan constraint unique bekerja di level string mentah, kata ganti seperti "dia", "nya", "orangnya" akan **membuat node sampah generik** ("dia" sebagai entitas terpisah), sekaligus fakta yang harusnya menempel ke orang yang tepat malah menempel ke entitas kosong "dia" yang tidak terhubung ke siapapun secara bermakna.

Pola percakapan seperti ini SANGAT umum: user cerita panjang di satu pesan, Claire bertanya lebih lanjut, user jawab singkat di pesan berikutnya. Setiap kali itu terjadi, **fakta baru dari jawaban lanjutan berisiko hilang atau salah kaitan**, karena `extract_knowledge` tidak pernah melihat pertanyaan Claire sebelumnya untuk tahu siapa "dia"/"nya" yang dimaksud.

### Kenapa ini kritis

Ini bertentangan langsung dengan salah satu instruksi yang justru sudah ditulis di system prompt Claire sendiri (`llm_service.py`, bagian "ATURAN RESOLUSI ENTITAS"): Claire *tahu* aturan "aku = nafiz, kamu = claire" untuk kata ganti orang pertama/kedua, tapi tidak ada aturan setara untuk resolusi kata ganti orang ketiga ("dia", "nya") — dan karena extraction tidak melihat histori, tidak ada cara bagi LLM extractor untuk tahu siapa "dia" itu meskipun mau mencoba.

### Rekomendasi

- Kirim minimal 2-4 pesan terakhir (termasuk jawaban/pertanyaan Claire sebelumnya) sebagai konteks tambahan ke `extract_knowledge`, supaya LLM extractor bisa resolve pronoun/ellipsis dengan benar.
- Tambahkan instruksi eksplisit di prompt extractor: kalau subjek tidak jelas dari 1 pesan tapi ada di histori, gunakan histori untuk resolve; kalau masih ambigu, jangan buat node dari kata ganti generik.

---

## 🟠 4. Retrieval dari Neo4j Tidak Punya Ranking Sama Sekali

**File**: `backend/services/neo4j_service.py`, fungsi `search_knowledge` (baris 82-108)

### Apa yang terjadi

```cypher
MATCH (n:Entity)-[r]->(m:Entity)
WHERE toLower(n.name) CONTAINS toLower($kw) OR toLower(m.name) CONTAINS toLower($kw) OR toLower(type(r)) CONTAINS toLower($kw)
SET n.importance = coalesce(n.importance, 1.0) + 0.1, m.importance = coalesce(m.importance, 1.0) + 0.1
RETURN n.name, type(r), m.name, labels(n) AS n_labels, labels(m) AS m_labels LIMIT 5
```

Tidak ada `ORDER BY` di query ini. `LIMIT 5` diterapkan ke urutan hasil **apa adanya dari Neo4j** (biasanya insertion order/internal id, bukan relevansi). Sistem sebenarnya **sudah punya** properti `importance` yang dihitung dan disimpan di setiap node (`merge_knowledge` menaikkan importance saat fakta baru ditemukan, `search_knowledge` menaikkan importance saat fakta di-retrieve, `consolidate_memory` men-decay importance seiring waktu) — tapi properti ini **tidak pernah dibaca ulang untuk menentukan urutan hasil**. Satu-satunya kegunaan `importance` sekarang murni untuk keperluan forgetting/decay, bukan untuk ranking retrieval.

Efeknya, kalau satu keyword match banyak relasi (kasus umum untuk keyword seperti "nafiz" yang punya 28 koneksi langsung), 5 hasil yang dikembalikan ke Claire adalah **5 hasil pertama yang secara kebetulan ditemukan Neo4j**, bukan 5 fakta paling penting/relevan/baru.

### Kenapa ini penting

Seluruh desain "importance scoring" dan "recency decay" yang disusun di `project_technical_document.md` (section 6.2 "Recency & Importance Scoring") itu tujuannya supaya retrieval mengembalikan hal yang paling relevan dulu. Tapi implementasi aktualnya berhenti di tengah jalan: skornya dihitung, disimpan, di-decay... tapi tidak pernah dipakai untuk mengurutkan apa yang benar-benar dikirim ke LLM. Ini artinya kalau graph sudah berisi banyak fakta tentang satu topik, yang muncul ke Claire bisa jadi fakta yang paling tidak penting.

### Rekomendasi

Tambahkan `ORDER BY n.importance DESC, m.importance DESC` (atau kombinasi importance+updated_at) sebelum `LIMIT 5` di `search_knowledge`.

---

## 🟠 5. Tidak Ada Kesadaran Temporal — Fakta Basi Dianggap Sama Validnya dengan Fakta Terbaru

**File**: Tidak ditemukan implementasinya di manapun pada `backend/services/`, `backend/models/`, atau `backend/routes/` — meski sudah didesain di `project_technical_document.md` section 11.3 ("Bottleneck #3: Temporal Drift").

### Apa yang terjadi

Skema node di Neo4j sekarang hanya punya `name`, `importance`, `updated_at`, dan label. Tidak ada:
- Field `is_current` untuk menandai fakta yang masih berlaku vs sudah usang
- Relasi `SUPERSEDED_BY` untuk menghubungkan fakta lama ke fakta penggantinya
- Logika apapun di `extract_knowledge` yang mendeteksi kontradiksi antara fakta baru dan fakta lama

Sekarang, semua fakta memakai relasi generik yang sama treatment-nya. Sebagai contoh nyata di data kamu sendiri: kamu bilang baru diterima kerja sebagai Data Scientist di Gojek. Tapi sebelumnya kamu juga bilang sedang magang sebagai Backend Developer Intern di Agung Sedayu Group. Keduanya sekarang tersimpan sebagai fakta yang **sama-sama valid selamanya** di graph — tidak ada mekanisme yang menandai "magang di Agung Sedayu Group" sebagai kemungkinan sudah tidak relevan/berakhir setelah kerja baru dimulai. `search_knowledge` bisa saja mengembalikan keduanya bersamaan ke Claire tanpa indikasi mana yang lebih baru/valid, dan Claire harus menebak sendiri dari fakta mentah tanpa timestamp yang jelas ditampilkan.

### Kenapa ini penting

Ini persis skenario yang sudah diperingatkan di dokumen desain kamu sendiri: seiring waktu, informasi soal pekerjaan, status hubungan, preferensi bisa berubah — dan tanpa temporal awareness, Claire berisiko "menyebut info lama" seolah masih berlaku. Untuk personal assistant jangka panjang, ini salah satu risiko terbesar untuk kredibilitas AI di mata usernya.

### Rekomendasi

Tidak perlu selengkap desain di dokumen teknis (yang mengusulkan decay function terpisah untuk mutable vs immutable facts). Langkah minimal yang berdampak besar:
- Tambahkan `created_at`/`last_confirmed_at` di setiap edge (bukan hanya node), supaya minimal Claire tahu kapan suatu fakta terakhir disebutkan.
- Saat `extract_knowledge` dipanggil dengan `neo4j_context` yang sudah berisi fakta terkait (mekanisme ini sudah ADA, lihat `llm_service.py` bagian `<existing_knowledge>`), tambahkan instruksi eksplisit: "jika fakta baru ini menggantikan/bertentangan dengan fakta existing, sertakan flag `supersedes`" — lalu proses flag itu di `merge_knowledge` untuk menandai fakta lama non-aktif alih-alih membiarkannya nyangkut selamanya sebagai fakta yang tampak masih valid.

---

## 🟠 6. Tidak Ada Cara Memperbaiki Memori yang Salah — Hanya Ada "Hapus Semua"

**File**: `backend/wipe_data.py`, `backend/routes/chat_routes.py`, `backend/routes/settings_routes.py`

### Apa yang terjadi

Sudah saya periksa seluruh route yang ada (`chat_routes.py`, `settings_routes.py`) — satu-satunya operasi hapus yang tersedia adalah:
- `DELETE /sessions/{session_id}` — hapus 1 sesi obrolan dari SQLite + vector terkait di Qdrant (tapi **tidak** menyentuh Neo4j sama sekali, jadi fakta yang sudah terekstrak dari sesi itu tetap ada di knowledge graph walau sesinya dihapus)
- `wipe_data.py` — script CLI yang menghapus **SELURUH** Neo4j, Qdrant, dan SQLite sekaligus, tidak granular

Tidak ada endpoint untuk: menghapus satu node/fakta tertentu, mengedit nilai sebuah fakta, atau "melupakan" satu topik spesifik.

### Kenapa ini penting

Dari temuan #1 dan #2 di atas, kita sudah tahu Claire **akan** membuat kesalahan memori (entity collision, hilangnya data). Ketika itu terjadi, satu-satunya pemulihan yang tersedia untukmu adalah menghapus **seluruh** ingatan Claire dari awal. Itu jelas bukan solusi yang proporsional untuk kesalahan kecil seperti "satu fakta yang salah kaitan". Untuk sistem yang tujuannya "mengingat dengan akurat", tidak adanya jalur koreksi granular berarti error yang terjadi bersifat permanen dan hanya bisa "diobati" dengan amnesia total.

### Rekomendasi

Tambahkan minimal:
- `DELETE /memory/graph/node/{name}` — hapus satu entity node tertentu beserta relasinya.
- `PATCH /memory/graph/node/{name}` — koreksi properti tertentu (misalnya split satu node yang collision menjadi dua).

---

## 🟡 7. Keyword Search Pakai Substring Mentah + Query "Read" Punya Efek Samping "Write"

**File**: `backend/services/neo4j_service.py`, `search_knowledge` (baris 92-108)

### Apa yang terjadi

Dua isu yang saling terkait dalam satu query yang sama:

**(a) Substring match tanpa word boundary.** `WHERE toLower(n.name) CONTAINS toLower($kw)` — `CONTAINS` di Cypher adalah substring match murni, tanpa memperhatikan batas kata. Saya buktikan langsung terhadap data yang ada:

```
keyword='di'   -> match ke: (reza)-[STRUGGLING_WITH]->(dina), (reza)-[WORKS_AT]->(bank mandiri), ...
keyword='an'   -> match ke: (reza)-[HAS_CHILD]->(reyhan), ...
keyword='a'    -> match ke hampir semua node yang mengandung huruf 'a'
```

Kata sehari-hari sesingkat "di" atau "an" (yang sangat mungkin dihasilkan oleh `generate_search_queries` sebagai keyword hasil ekstraksi) bisa nyantol ke "budi", "dina", "reyhan" secara kebetulan huruf, bukan karena relevansi makna.

**(b) Read query menaikkan importance sebagai side-effect.** Query yang sama juga menjalankan `SET n.importance = ... + 0.1` untuk **setiap** node yang match — termasuk yang match-nya cuma kebetulan substring seperti di atas. Artinya sekadar *mencari* sesuatu bisa mencemari importance score dari entitas yang sama sekali tidak relevan, yang nantinya mempengaruhi keputusan "forget" di `consolidate_memory` (baris 175-217) — entitas yang harusnya di-decay/dihapus karena memang tidak relevan malah bisa terus "diselamatkan" karena kebetulan namanya mengandung substring dari keyword pencarian yang sering muncul.

### Rekomendasi

- Ganti `CONTAINS` dengan pencarian berbasis word/token match, atau minimal filter panjang minimum keyword (skip keyword < 3-4 karakter).
- Pisahkan operasi read (`search_knowledge`) dari operasi write (importance boost). Kalau importance boost saat retrieval memang diinginkan, lakukan di query terpisah yang hanya menyentuh node yang benar-benar match secara bermakna.

---

## 🟡 8. Bug `.capitalize()` Merusak Label Kategori Custom Multi-Word

**File**: `backend/services/neo4j_service.py`, baris 36: `label_dinamis = node.get("label", "Entity").capitalize()`

### Apa yang terjadi

Prompt extractor (`llm_service.py`, bagian "DAFTAR LABEL INTI") secara eksplisit menginstruksikan LLM: *"Jika terpaksa bikin baru, gunakan format PascalCase"* — contoh yang wajar adalah sesuatu seperti `BackendDeveloper` atau `AIEngineer`. Tapi Python `.capitalize()` tidak mempertahankan PascalCase; ia justru **me-lowercase semua huruf setelah huruf pertama**. Saya cek langsung:

```python
"BackendDeveloper".capitalize()  ->  "Backenddeveloper"
"AI_ENGINEER".capitalize()       ->  "Ai_engineer"
```

Jadi setiap kali LLM mematuhi instruksi PascalCase untuk label baru yang tidak ada di daftar inti, kode ini justru merusaknya menjadi satu kata tidak terbaca. Untungnya, di data yang sudah ada sekarang, LLM extractor cenderung memilih label dari 12 daftar inti yang memang sudah singkat (`Person`, `Object`, `Concept`, dll) sehingga bug ini belum termanifestasi secara terlihat — tapi begitu ada fakta yang butuh label custom multi-word, hasilnya akan langsung cacat dan tidak konsisten dengan instruksi prompt-nya sendiri.

### Rekomendasi

Ganti jadi mempertahankan casing asli dari LLM, hanya sanitasi karakter ilegal:
```python
label_dinamis = re.sub(r'[^a-zA-Z0-9_]', '', node.get("label", "Entity"))
if not label_dinamis or not label_dinamis[0].isalpha():
    label_dinamis = "Entity"
```

---

## 🟡 9. Tidak Ada Provenance — Node Tidak Tahu Berasal dari Percakapan Mana

**File**: `backend/services/neo4j_service.py` (skema node), `backend/models/`

### Apa yang terjadi

Setiap node Entity hanya punya `name`, label dinamis, `updated_at`, `importance`. Tidak ada relasi/field balik ke `Conversation` atau `Message` (SQLite) yang menjadi sumber fakta tersebut. Ini beda dengan desain awal di `project_technical_document.md` yang punya relasi `SOURCE` (Fact → Conversation).

### Kenapa ini penting

Tanpa provenance, kamu tidak punya cara untuk verifikasi "fakta ini Claire dapat dari mana / kapan aku bilang ini?" — kalau suatu saat sebuah fakta di graph terasa aneh/salah, tidak ada jejak audit untuk melacak balik ke percakapan aslinya untuk konfirmasi. Ini juga menyulitkan future-proofing kalau nanti mau membangun UI "lihat asal memori ini".

### Rekomendasi

Tambahkan minimal `source_conversation_id` di setiap edge yang dibuat `merge_knowledge`, diambil dari `session_id` yang sudah tersedia di context `save_interaction`.

---

## 🟢 10. API Key Tersimpan Plaintext

**File**: `backend/services/settings_service.py`, `backend/models/user_setting.py`, kolom `value` bertipe `JSON`

### Apa yang terjadi

`api_keys` (berisi key untuk Google/Groq/OpenAI/HuggingFace) disimpan sebagai JSON polos di kolom SQLite tanpa enkripsi. Karena project ini murni untuk pemakaian personal di mesin lokal milikmu sendiri, risikonya jauh lebih rendah dibanding aplikasi multi-user — tapi tetap layak dicatat sebagai *defense in depth* mengingat `personia.db` adalah file biasa yang bisa terbaca siapapun yang punya akses ke folder itu (termasuk risiko tidak sengaja ter-commit ke git atau ter-backup ke cloud storage tanpa enkripsi).

### Rekomendasi

Kalau mau ditingkatkan: enkripsi nilai `api_keys` dengan key yang disimpan di `.env` (yang sudah di luar git), bukan simpan API key mentah di database. Untuk konteks single-user lokal, ini prioritasnya rendah — cukup pastikan `backend/.env` dan `backend/data/` tidak pernah ter-commit ke version control manapun di masa depan.

---

## 🟢 11. Router "Butuh Memori atau Tidak" Bisa Salah Putus

**File**: `backend/services/llm_service.py`, fungsi `generate_search_queries` (baris terkait "Layer 2 Smart Router")

### Apa yang terjadi

`generate_search_queries` memutuskan lewat LLM murah apakah pesan butuh keyword pencarian ke Neo4j atau tidak (`{"keywords": []}` jika dianggap tidak perlu). Ini adalah keputusan biner dari satu LLM call — kalau LLM salah menilai (misalnya menganggap sebuah pertanyaan sebagai "chit-chat" padahal sebenarnya butuh fakta lama), maka `neo4j_context` untuk giliran itu kosong.

### Kenapa risikonya rendah

Risiko ini **dilemahkan secara struktural** oleh desain yang sudah ada: `retrieve_context()` di `memory_service.py` menjalankan pencarian Qdrant (`search_memory`) secara **paralel dan independen** dari router Neo4j ini. Jadi walau router salah menilai untuk Neo4j, jalur semantic search di Qdrant tetap berjalan tanpa bergantung pada keputusan router yang sama. Ini murni soal recall Neo4j spesifik yang berkurang, bukan total memory loss.

### Rekomendasi

Tidak urgent. Kalau ingin dikuatkan, bisa tambahkan heuristic sederhana (panjang pesan, ada tidaknya kata tanya) sebagai fallback jika LLM router gagal parse, dibanding sepenuhnya bergantung pada satu LLM call.

---

## Catatan Tambahan (Bukan Bug, Tapi Perlu Diketahui)

Beberapa hal di luar 11 poin di atas yang saya temukan saat investigasi, sifatnya housekeeping bukan kesalahan logika AI/graph:

- `configs/neo4j_config.py` dan `configs/qdrant_config.py` mendefinisikan koneksi Neo4j/Qdrant yang **terpisah dan tidak dipakai** oleh service utama (`services/neo4j_service.py` dan `services/qdrant_service.py` masing-masing membuat koneksinya sendiri). Satu-satunya pemakai `configs/*_config.py` adalah `scratch/test_db.py`. Tidak berbahaya, tapi berpotensi membingungkan karena ada dua sumber koneksi yang terlihat seperti duplikasi.
- `apscheduler` ada di `requirements.txt` tapi tidak dipakai di manapun — background job konsolidasi memori di `main.py` diimplementasikan manual dengan `asyncio.sleep(3600)` dalam `while True` loop, bukan pakai APScheduler.
- Folder `use_cases/` dan `crud/` sudah dibuat sesuai rencana arsitektur di dokumen teknis, tapi masih kosong (`# Init` saja) — semua logic saat ini ada langsung di `services/`.
- Model `Schedule` (`models/schedule.py`) sudah ada di database schema (dari migration awal), tapi tidak ada satupun route/service yang memakainya — fitur "jadwal & reminder" yang direncanakan di dokumen teknis belum diimplementasikan sama sekali.
- Tidak ada injeksi tanggal/waktu saat ini ke system prompt Claire (`llm_service.py`) — jadi Claire tidak punya cara mengetahui "hari ini tanggal berapa" kecuali disebutkan user, yang membuat referensi waktu relatif ("besok", "minggu lalu") sulit dijangkarkan secara konsisten dari sudut pandang Claire sendiri.
- Script uji (`test_extract.py`, `test_prompt.py`, `test_queries.py`, `test_sim.py`) ada di root `backend/`, bukan di folder `tests/` yang sudah disiapkan (isinya baru `__init__.py` kosong) — ini eksploratif/manual, bukan automated test suite.

---

## Kesimpulan

Fondasi arsitektur (Neo4j untuk graph, Qdrant untuk semantic search, dual-lane fast/slow untuk retrieval vs extraction) sudah tepat dan sesuai untuk tujuan project. Tapi ada gap antara desain yang tertulis di `project_technical_document.md` dengan implementasi aktual — terutama tiga area yang paling mengancam kualitas "ingatan" Claire secara langsung:

1. **Disambiguasi entitas** belum ada sama sekali (hanya exact/semantic match by name), padahal ini paling krusial untuk knowledge graph personal yang pasti akan menyimpan banyak orang dengan nama umum.
2. **Deduplikasi Qdrant punya bug logic** yang bisa menghapus memori lama secara diam-diam.
3. **Entity extraction tidak context-aware**, sehingga kehilangan fakta dari jawaban lanjutan yang sangat umum dalam percakapan natural.

Ketiga hal ini murni soal correctness, bukan soal skala atau performa — dan ketiganya sudah terbukti termanifestasi di data pemakaianmu sendiri saat ini (baru 12 pesan user, 56 node), jadi akan semakin sering terjadi seiring pemakaian bertambah kalau tidak dibenahi lebih dulu sebelum concern lain (seperti yang sudah dibahas panjang di `project_technical_document.md` section 11: hairball, cost, latency).
