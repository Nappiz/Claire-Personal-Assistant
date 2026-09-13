"""Deprecated audit/test facade. No runtime consumer; single implementation owners."""
from app.compatibility import install_facade
from app.domain.web import intent_policy, url_policy, ranking
from app.infrastructure.web import searxng_gateway, search_results
install_facade(__name__, {
    "WebSearchPlan": (intent_policy, "WebSearchPlan"),
    "plan_web_search": (intent_policy, "plan_web_search"),
    "plan_web_search_with_context": (intent_policy, "plan_web_search_with_context"),
    "normalize_public_url": (url_policy, "normalize_public_url"),
    "_tfidf_terms": (ranking, "tfidf_terms"),
    "_rank_results_by_tfidf": (ranking, "rank_results_by_tfidf"),
    "_merge_result_groups": (ranking, "merge_result_groups"),
    "_clean_text": (search_results, "clean_text"),
    "_parse_results": (search_results, "parse_results"),
    "retrieve_web_context": (searxng_gateway, "retrieve_web_context"),
    "settings": (searxng_gateway, "settings"),
    "httpx": (searxng_gateway, "httpx"),
    "random": (searxng_gateway, "random"),
    "asyncio": (searxng_gateway, "asyncio"),
    "_SEARCH_ENGINES": (searxng_gateway, "_SEARCH_ENGINES"),
    "_USER_AGENTS": (searxng_gateway, "_USER_AGENTS"),
    "datetime": (searxng_gateway, "datetime"),
    "_TFIDF_TOKEN_RE": (ranking, "_TFIDF_TOKEN_RE"),
    "_TFIDF_STOPWORDS": (ranking, "_TFIDF_STOPWORDS"),
    "_ALLOWED_ENGINE_NAMES": (search_results, "_ALLOWED_ENGINE_NAMES"),
})
