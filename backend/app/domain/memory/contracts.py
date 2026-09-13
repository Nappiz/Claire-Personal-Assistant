import re

class TurnConflictError(RuntimeError):
    """Raised when one conversation already has another unfinished turn."""

MEMORY_RECALL_RE = re.compile(
    r"\b(ingat|inget|pernah (?:aku|saya|gw|gue) (?:bilang|cerita)|"
    r"favoritku|kesukaanku|alergiku|ulang tahunku|lahirku|"
    r"siapa (?:pacar|teman|temen|ibu|ayah)ku|"
    r"(?:aku|saya|gw|gue) (?:kerja|tinggal|kuliah) (?:di )?(?:mana|dimana))\b"
)

HISTORICAL_RE = re.compile(r"\b(dulu|pernah|sebelumnya|riwayat|kapan terakhir|waktu itu)\b")

SEARCH_STOPWORDS = {
    "yang", "dan", "atau", "dari", "untuk", "dengan", "apa", "siapa", "kapan",
    "dimana", "mana", "apakah", "kamu", "masih", "ingat", "inget", "tentang", "aku",
    "saya", "gw", "gue", "nih", "dong", "deh", "kok", "ya", "itu", "ini", "pernah",
}

VAGUE_PROJECT_REFERENCE_RE = re.compile(
    r"\b(?:project|proyek|projek)(?:\s*-?\s*(?:ku|saya|aku|gw|gue|milikku|ini|itu|tersebut))\b",
    flags=re.IGNORECASE,
)

MEMORY_RETRY_BASE_SECONDS = 30

MEMORY_RETRY_MAX_SECONDS = 60 * 60

MEMORY_JOB_LEASE_SECONDS = 5 * 60
