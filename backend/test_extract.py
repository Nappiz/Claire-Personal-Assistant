import os
from services.llm_service import extract_knowledge
import json

stress_test_msg = (
    "Kemarin temenku namanya Budi nikah sama Siska. Mereka resepsi di Hotel Mulia Jakarta "
    "tanggal 12 Agustus 2024, biayanya sampe 500 juta rupiah. Budi itu kerja sebagai CEO di "
    "startup Fintech OVO, sedangkan Siska berprofesi sebagai Dokter Gigi di RS Siloam. "
    "Siska punya phobia sama kucing dan alergi parah sama seafood, padahal Budi miara 3 "
    "kucing persia di rumah barunya di Kemang. Oiya, Budi barusan ngebeliin mobil Tesla "
    "Model 3 warna merah buat kado ulang tahun Siska yang ke-25."
)

print("Menjalankan Ekstraksi...")
res = extract_knowledge(stress_test_msg)

print("\nHasil Ekstraksi JSON:")
print(json.dumps(res, indent=2))
