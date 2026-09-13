"""Conservative query-provenance checks, separate from lexical ranking."""
import re
from app.domain.web.ranking import tfidf_terms

_MODIFIERS = frozenset("""
harga price prices tarif berita news terbaru terkini latest current today sekarang
skrg saat hari ini bulan month tahun year daftar list informasi information info
status operasional operasi apakah berapa bagaimana update updated september oktober
januari februari maret april mei juni juli agustus november desember season patch
tolong please aku saya kamu minta suruh coba lebih strict lagi dong web internet cari
""".split())


def search_topic_terms(query):
    # No brand, game, vendor, or source-domain weights. Strip generic modifiers.
    return {term for term in tfidf_terms(query) if "::" not in term
            and term not in _MODIFIERS and not term.isdigit()}


def query_matches_topic(query, target):
    anchors = search_topic_terms(target)
    if not anchors:
        return True
    query_terms = search_topic_terms(query)
    # Acronyms and ordinary plural variants permit query rewrites (e.g. a
    # product's abbreviation expanded by the model), not fixed product aliases.
    words = re.findall(r"[a-z]+", query.casefold())
    query_terms |= {"".join(word[0] for word in words[index:index + size])
                    for size in (2, 3) for index in range(len(words) - size + 1)}
    normalized = {word[:-2] if word.endswith("es") else word[:-1]
                  if word.endswith("s") else word for word in query_terms}
    return bool(anchors & (query_terms | normalized))


def filter_search_evidence(results, query):
    anchors = search_topic_terms(query)
    if not anchors:
        return []
    required_years = [int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", query)]
    selected = []
    for result in results:
        text = f"{result.title} {result.snippet} {result.url}"
        # A lone shared location/generic word must not validate a multi-topic
        # query. This remains a conservative lexical gate, not semantic proof.
        if len(anchors & search_topic_terms(text)) < min(2, len(anchors)):
            continue
        dated = [int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b",
                 f"{text} {result.published_at or ''}")]
        if required_years and dated and max(dated) < max(required_years):
            continue
        selected.append(result)
    return selected


def web_evidence_unavailable(context):
    return context.status != "ok" or not context.results


def unavailable_web_answer(context):
    if context.status == "disabled":
        return "Pencarian web sedang dinonaktifkan, jadi aku belum bisa memverifikasi informasi terbaru ini."
    if context.status == "unavailable":
        return "Layanan pencarian web sedang tidak tersedia. Aku belum bisa memastikan informasi terbaru ini dan tidak akan menebaknya."
    return "Aku belum menemukan sumber web yang relevan untuk memastikan informasi ini. Coba perjelas objek, wilayah, atau periode yang kamu maksud."
