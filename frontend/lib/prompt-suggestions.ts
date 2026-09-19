export type PromptSuggestion = {
  title: string;
  desc: string;
  prompt: string;
};

// Local-only suggestion catalogue. It is intentionally static so opening the
// empty state never consumes an LLM request or depends on network availability.
export const PROMPT_SUGGESTIONS: readonly PromptSuggestion[] = [
  { title: "Susun hari ini", desc: "Prioritaskan tugas yang paling penting", prompt: "Bantu susun prioritas aku untuk hari ini." },
  { title: "Rencana besok", desc: "Buat jadwal yang realistis", prompt: "Buatkan jadwal produktif untuk besok." },
  { title: "Weekly reset", desc: "Rapikan fokus minggu ini", prompt: "Bantu aku bikin weekly reset dan prioritas minggu ini." },
  { title: "Time blocking", desc: "Bagi waktu tanpa bikin capek", prompt: "Buatkan time block untuk pekerjaan dan istirahat hari ini." },
  { title: "Rencana akhir pekan", desc: "Seimbang antara produktif dan santai", prompt: "Kasih ide rencana akhir pekan yang produktif tapi santai." },
  { title: "To-do sederhana", desc: "Pecah tugas besar jadi kecil", prompt: "Bantu pecah tugas besar aku jadi to-do kecil yang bisa dikerjakan." },
  { title: "Atur deadline", desc: "Urutkan pekerjaan berdasarkan urgensi", prompt: "Bantu urutkan task aku berdasarkan deadline dan dampaknya." },
  { title: "Rutinitas pagi", desc: "Mulai hari lebih terarah", prompt: "Buatkan rutinitas pagi yang realistis buat aku." },
  { title: "Rutinitas malam", desc: "Tutup hari tanpa overthinking", prompt: "Buatkan rutinitas malam singkat supaya aku lebih tenang." },
  { title: "Fokus 90 menit", desc: "Siapkan sesi deep work", prompt: "Bantu siapkan rencana deep work 90 menit untuk aku." },

  { title: "Debug error", desc: "Bedah error dari kode atau log", prompt: "Bantu debug error ini, jelaskan akar masalah dan langkah perbaikannya." },
  { title: "Review kode", desc: "Cari bug dan improvement penting", prompt: "Tolong review kode aku, fokus ke bug dan hal yang paling perlu diperbaiki." },
  { title: "Desain API", desc: "Rancang endpoint yang rapi", prompt: "Bantu desain REST API untuk fitur yang sedang aku buat." },
  { title: "Optimasi query", desc: "Buat akses database lebih sehat", prompt: "Bantu optimasi query database aku dan jelaskan trade-off-nya." },
  { title: "Refactor aman", desc: "Rapikan tanpa mengubah perilaku", prompt: "Bantu buat rencana refactor yang aman untuk kode aku." },
  { title: "Tulis unit test", desc: "Cari skenario yang wajib diuji", prompt: "Bantu tentukan unit test penting untuk fitur yang aku buat." },
  { title: "Jelaskan stack trace", desc: "Ubah error jadi langkah konkret", prompt: "Jelaskan stack trace ini dengan bahasa sederhana dan kasih langkah fix." },
  { title: "Arsitektur backend", desc: "Pilih struktur yang scalable", prompt: "Bantu pikirkan arsitektur backend untuk fitur baru ini." },
  { title: "SQL dari nol", desc: "Bantu tulis query yang tepat", prompt: "Bantu tulis query SQL untuk kebutuhan ini." },
  { title: "Regex helper", desc: "Buat pola yang mudah dirawat", prompt: "Bantu buat regex untuk kasus ini dan jelaskan cara kerjanya." },

  { title: "Tulis email", desc: "Buat pesan profesional tapi natural", prompt: "Bantu tulis email profesional untuk situasi ini." },
  { title: "Balas chat", desc: "Cari wording yang pas", prompt: "Bantu aku membalas chat ini dengan nada yang natural." },
  { title: "Follow-up sopan", desc: "Ingatkan tanpa terdengar memaksa", prompt: "Bantu tulis pesan follow-up yang sopan." },
  { title: "Pesan LinkedIn", desc: "Mulai networking dengan santai", prompt: "Bantu tulis pesan LinkedIn untuk mulai networking." },
  { title: "Bio singkat", desc: "Ringkas profil diri dengan kuat", prompt: "Bantu buat bio singkat yang profesional untuk aku." },
  { title: "Caption posting", desc: "Tulis caption yang tidak kaku", prompt: "Bantu buat beberapa pilihan caption untuk postingan ini." },
  { title: "Proposal singkat", desc: "Susun pitch yang jelas", prompt: "Bantu buat kerangka proposal singkat untuk ide ini." },
  { title: "Bikin presentasi", desc: "Tentukan alur slide yang kuat", prompt: "Bantu buat outline presentasi untuk topik ini." },
  { title: "Ringkas dokumen", desc: "Ambil poin yang benar-benar penting", prompt: "Bantu ringkas dokumen ini menjadi poin-poin penting." },
  { title: "Perbaiki tulisan", desc: "Buat lebih jelas dan enak dibaca", prompt: "Tolong perbaiki tulisan aku agar lebih jelas dan natural." },

  { title: "Ide kado", desc: "Cari hadiah yang terasa personal", prompt: "Kasih ide kado ulang tahun yang personal untuk sahabat." },
  { title: "Menu hari ini", desc: "Pilih makanan yang gampang diputuskan", prompt: "Bantu aku memilih ide makan hari ini." },
  { title: "Rencana jalan", desc: "Susun agenda hangout yang seru", prompt: "Kasih ide agenda hangout yang seru dan tidak ribet." },
  { title: "Rekomendasi film", desc: "Cari tontonan sesuai mood", prompt: "Rekomendasikan film sesuai mood aku malam ini." },
  { title: "Rekomendasi musik", desc: "Temani kerja atau santai", prompt: "Kasih rekomendasi musik untuk nemenin aku fokus." },
  { title: "Ide weekend date", desc: "Buat momen sederhana terasa spesial", prompt: "Kasih ide weekend date yang sederhana tapi seru." },
  { title: "Packing checklist", desc: "Jangan ada barang penting tertinggal", prompt: "Bantu buat packing checklist untuk perjalanan singkat." },
  { title: "Rencana liburan", desc: "Mulai dari itinerary sederhana", prompt: "Bantu buat itinerary liburan singkat yang santai." },
  { title: "Pilih outfit", desc: "Sesuaikan dengan acara dan cuaca", prompt: "Bantu pilih outfit untuk acara ini." },
  { title: "Ide hobi", desc: "Cari kegiatan baru yang cocok", prompt: "Kasih ide hobi baru yang mungkin cocok buat aku." },

  { title: "Belajar topik baru", desc: "Buat roadmap yang tidak membingungkan", prompt: "Bantu buat roadmap belajar untuk topik baru ini." },
  { title: "Jelaskan konsep", desc: "Uraikan dari dasar sampai paham", prompt: "Jelaskan konsep ini dari dasar dengan contoh sederhana." },
  { title: "Latihan interview", desc: "Simulasikan pertanyaan dan jawaban", prompt: "Ayo simulasi interview kerja untuk posisi backend engineer." },
  { title: "Belajar bahasa Inggris", desc: "Latihan percakapan santai", prompt: "Ajak aku latihan bahasa Inggris lewat percakapan santai." },
  { title: "Quiz cepat", desc: "Uji pemahaman tanpa tegang", prompt: "Buatkan quiz singkat untuk menguji pemahaman aku tentang topik ini." },
  { title: "Belajar system design", desc: "Bedah satu kasus nyata", prompt: "Ajari aku system design lewat satu studi kasus nyata." },
  { title: "Pahami algoritma", desc: "Fokus ke intuisi, bukan hafalan", prompt: "Jelaskan algoritma ini dengan intuisi dan contoh." },
  { title: "Roadmap karier", desc: "Tentukan skill berikutnya", prompt: "Bantu buat roadmap skill untuk perkembangan karier aku." },
  { title: "Review CV", desc: "Perkuat cerita dan pencapaian", prompt: "Bantu review CV aku dan kasih saran yang konkret." },
  { title: "Belajar konsisten", desc: "Buat sistem kecil yang jalan", prompt: "Bantu aku bikin sistem belajar yang konsisten." },

  { title: "Brainstorm ide", desc: "Cari banyak kemungkinan dulu", prompt: "Ayo brainstorm beberapa ide untuk proyek baru." },
  { title: "Validasi ide", desc: "Uji asumsi paling berisiko", prompt: "Bantu validasi ide produk ini dan asumsi yang perlu diuji." },
  { title: "Nama proyek", desc: "Cari nama yang mudah diingat", prompt: "Kasih ide nama untuk proyek ini." },
  { title: "Fitur MVP", desc: "Pilih yang paling bernilai", prompt: "Bantu tentukan fitur MVP paling penting untuk ide ini." },
  { title: "User flow", desc: "Rapikan perjalanan pengguna", prompt: "Bantu susun user flow untuk fitur ini." },
  { title: "Tulis PRD", desc: "Buat requirement lebih jelas", prompt: "Bantu buat kerangka PRD untuk fitur ini." },
  { title: "Analisis kompetitor", desc: "Temukan celah yang menarik", prompt: "Bantu buat framework analisis kompetitor untuk produk ini." },
  { title: "Prioritas fitur", desc: "Pilih impact terbesar", prompt: "Bantu prioritaskan fitur dengan framework yang sederhana." },
  { title: "Cari risiko", desc: "Antisipasi masalah dari awal", prompt: "Bantu identifikasi risiko utama dari rencana ini." },
  { title: "Decision matrix", desc: "Bandingkan pilihan lebih objektif", prompt: "Bantu buat decision matrix untuk memilih di antara beberapa opsi." },

  { title: "Atur budget", desc: "Bikin rencana pengeluaran", prompt: "Bantu aku membuat budget sederhana untuk bulan ini." },
  { title: "Bandingkan produk", desc: "Pilih berdasarkan kebutuhan nyata", prompt: "Bantu bandingkan beberapa produk yang sedang aku pertimbangkan." },
  { title: "Rencana nabung", desc: "Tentukan target yang masuk akal", prompt: "Bantu buat rencana menabung untuk target ini." },
  { title: "Hitung patungan", desc: "Bagi biaya dengan adil", prompt: "Bantu hitung pembagian biaya patungan ini." },
  { title: "Evaluasi langganan", desc: "Cari biaya yang bisa dipangkas", prompt: "Bantu aku evaluasi langganan bulanan yang perlu dipertahankan." },
  { title: "Rencana belanja", desc: "Bedakan butuh dan ingin", prompt: "Bantu susun prioritas belanja aku bulan ini." },
  { title: "Target finansial", desc: "Pecah target jadi langkah kecil", prompt: "Bantu pecah target finansial aku jadi langkah bulanan." },
  { title: "Simulasi pilihan", desc: "Lihat trade-off sebelum memutuskan", prompt: "Bantu aku melihat trade-off dari pilihan ini." },
  { title: "Checklist pindahan", desc: "Atur hal penting sebelum pindah", prompt: "Bantu buat checklist untuk persiapan pindahan." },
  { title: "Rencana beli barang", desc: "Tentukan kapan waktu yang tepat", prompt: "Bantu aku menilai apakah sekarang waktu yang tepat membeli barang ini." },

  { title: "Curhat sebentar", desc: "Rapikan pikiran yang lagi penuh", prompt: "Aku lagi kepikiran banyak hal, boleh bantu aku mengurai pikiran ini?" },
  { title: "Cari perspektif", desc: "Lihat masalah dari sisi lain", prompt: "Bantu aku melihat situasi ini dari perspektif lain." },
  { title: "Bikin keputusan", desc: "Urai pilihan yang bikin bimbang", prompt: "Aku lagi bingung memilih, bantu aku berpikir jernih." },
  { title: "Kelola stres", desc: "Mulai dari langkah kecil sekarang", prompt: "Aku lagi stres, bantu aku menentukan langkah kecil yang bisa kulakukan sekarang." },
  { title: "Keluar dari stuck", desc: "Temukan langkah berikutnya", prompt: "Aku lagi stuck, bantu aku cari langkah berikutnya." },
  { title: "Refleksi hari ini", desc: "Lihat yang sudah berjalan baik", prompt: "Ajak aku refleksi singkat tentang hari ini." },
  { title: "Batasan sehat", desc: "Siapkan cara menyampaikannya", prompt: "Bantu aku menyusun batasan yang sehat untuk situasi ini." },
  { title: "Susun argumen", desc: "Sampaikan pendapat lebih jelas", prompt: "Bantu aku menyusun argumen yang jelas untuk pendapat ini." },
  { title: "Pecahkan konflik", desc: "Cari langkah komunikasi yang tenang", prompt: "Bantu aku memikirkan cara menyelesaikan konflik ini dengan baik." },
  { title: "Motivasi realistis", desc: "Kembali jalan tanpa kata-kata kosong", prompt: "Aku kehilangan semangat, bantu aku mulai lagi dengan cara yang realistis." },

  { title: "Rancang database", desc: "Tentukan tabel dan relasinya", prompt: "Bantu rancang schema database untuk fitur ini." },
  { title: "Buat migration plan", desc: "Ubah data tanpa downtime berantakan", prompt: "Bantu buat migration plan database yang aman." },
  { title: "Review security", desc: "Cari celah sebelum terlambat", prompt: "Bantu review risiko security dari fitur ini." },
  { title: "Tulis dokumentasi", desc: "Jelaskan fitur untuk developer lain", prompt: "Bantu tulis dokumentasi teknis untuk fitur ini." },
  { title: "Buat changelog", desc: "Ringkas perubahan yang penting", prompt: "Bantu buat changelog yang jelas dari perubahan ini." },
  { title: "Commit message", desc: "Tulis commit yang informatif", prompt: "Bantu buat commit message yang baik untuk perubahan ini." },
  { title: "PR description", desc: "Jelaskan perubahan dan dampaknya", prompt: "Bantu tulis pull request description untuk perubahan ini." },
  { title: "Rancang caching", desc: "Pilih strategi cache yang tepat", prompt: "Bantu pikirkan strategi caching untuk endpoint ini." },
  { title: "Observability", desc: "Tentukan log dan metric penting", prompt: "Bantu tentukan logging dan metric penting untuk fitur ini." },
  { title: "Incident checklist", desc: "Siapkan respons saat sistem bermasalah", prompt: "Bantu buat checklist penanganan incident untuk service ini." },

  { title: "Masak cepat", desc: "Cari ide makanan praktis", prompt: "Kasih ide masakan cepat dengan bahan yang umum ada." },
  { title: "Olahraga ringan", desc: "Mulai gerak tanpa ribet", prompt: "Buatkan ide olahraga ringan yang bisa aku lakukan hari ini." },
  { title: "Rencana tidur", desc: "Atur malam agar besok lebih segar", prompt: "Bantu aku memperbaiki jadwal tidur dengan langkah yang realistis." },
  { title: "Digital declutter", desc: "Rapikan file dan aplikasi", prompt: "Bantu buat checklist digital declutter untuk laptop dan HP aku." },
  { title: "Bersih-bersih kamar", desc: "Mulai dari area paling mudah", prompt: "Bantu buat rencana bersih-bersih kamar selama 30 menit." },
  { title: "Daftar bacaan", desc: "Cari bacaan untuk topik tertentu", prompt: "Rekomendasikan daftar bacaan untuk topik yang ingin aku pelajari." },
  { title: "Jurnal singkat", desc: "Mulai menulis tanpa tekanan", prompt: "Kasih aku beberapa prompt journaling untuk malam ini." },
  { title: "Kebiasaan baru", desc: "Bangun pelan-pelan tapi konsisten", prompt: "Bantu aku membangun kebiasaan baru yang realistis." },
  { title: "Rencana 30 hari", desc: "Fokus pada satu perubahan", prompt: "Bantu buat challenge 30 hari untuk tujuan ini." },
  { title: "Pertanyaan random", desc: "Mulai obrolan yang seru", prompt: "Tanya aku satu pertanyaan random yang seru buat dibahas." },
];

export function getRandomPromptSuggestions(count = 4): PromptSuggestion[] {
  const shuffled = [...PROMPT_SUGGESTIONS];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[randomIndex]] = [shuffled[randomIndex], shuffled[index]];
  }
  return shuffled.slice(0, Math.min(count, shuffled.length));
}
