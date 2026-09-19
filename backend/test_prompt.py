import sys
sys.path.append('.')
from services.llm_service import extract_knowledge

msg = 'Halo claire, yuk kenalan dulu, Nama ku Badruzzaman Nafiz dipanggil Nafiz, aku umur 21 tahun, aku lahir tanggal 10 Juni 2005 Aku saat ini masih Kuliah Semester 7 di ITS (Institut Teknologi Sepuluh Nopember) Surabaya dengan jurusan Teknik Informatika (Computer Science) Aku merupakan Software Engineer Backend Developer, aku juga AI Engineer Aku saat ini sedang magang di "Agung Sedayu Group" sebagai Backend Developer Intern'

print(extract_knowledge(msg, []))
