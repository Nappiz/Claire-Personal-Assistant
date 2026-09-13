import math
import re
from collections import Counter
from schemas.chat_sch import WebSearchResult

_TFIDF_TOKEN_RE = re.compile(r"[\w.+-]+", re.UNICODE)
_TFIDF_STOPWORDS = frozenset(
    {
        "a", "an", "and", "atau", "cari", "carikan", "dan", "dari", "di",
        "google", "googlekan", "googling", "ini", "itu", "ke", "of", "on",
        "pada", "the", "to", "untuk", "yang",
    }
)

def tfidf_terms(value: str) -> list[str]:
    """Return generic word and adjacent-word features without domain knowledge."""
    words = [
        token.lower()
        for token in _TFIDF_TOKEN_RE.findall(value)
        if len(token) >= 2 and token.lower() not in _TFIDF_STOPWORDS
    ]
    bigrams = [f"{left}::{right}" for left, right in zip(words, words[1:])]
    return words + bigrams


def rank_results_by_tfidf(
    results: list[WebSearchResult],
    query: str,
) -> list[WebSearchResult]:
    """Rank search snippets by cosine similarity in a small local TF-IDF corpus."""
    query_terms = tfidf_terms(query)
    if not results or not query_terms:
        return results

    document_terms = [
        tfidf_terms(f"{result.title} {result.snippet}")
        for result in results
    ]
    document_frequency: Counter[str] = Counter()
    for terms in document_terms:
        document_frequency.update(set(terms))

    document_count = len(document_terms)

    def vectorize(terms: list[str]) -> dict[str, float]:
        if not terms:
            return {}
        counts = Counter(terms)
        term_count = len(terms)
        return {
            term: (count / term_count)
            * (math.log((document_count + 1) / (document_frequency.get(term, 0) + 1)) + 1.0)
            for term, count in counts.items()
        }

    def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot_product = sum(weight * right.get(term, 0.0) for term, weight in left.items())
        if dot_product <= 0.0:
            return 0.0
        left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
        right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
        return dot_product / (left_norm * right_norm) if left_norm and right_norm else 0.0

    query_vector = vectorize(query_terms)
    ranked: list[tuple[float, int, WebSearchResult]] = []
    for index, (result, terms) in enumerate(zip(results, document_terms)):
        similarity = cosine_similarity(query_vector, vectorize(terms))
        # Lexical overlap is a ranking signal, not a relevance requirement:
        # translations and synonyms can have zero overlap with the goal.
        ranked.append((similarity, index, result))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [result for _, _, result in ranked]


def merge_result_groups(
    groups: list[list[WebSearchResult]],
    *,
    limit: int,
) -> list[WebSearchResult]:
    """Round-robin result groups so every generated query is represented."""
    merged: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    max_group_length = max((len(group) for group in groups), default=0)
    for index in range(max_group_length):
        for group in groups:
            if index >= len(group):
                continue
            result = group[index]
            if result.url in seen_urls:
                continue
            merged.append(result)
            seen_urls.add(result.url)
            if len(merged) >= limit:
                return merged
    return merged
