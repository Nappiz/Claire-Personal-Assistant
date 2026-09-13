"""Existing web implementation behind a workflow boundary; no algorithm changes."""
from app.infrastructure.web import page_reader, searxng_gateway
from app.domain.web import intent_policy, url_policy
from app.observability.operational_events import emit_event


class WebWorkflowGateway:
    async def retrieve_web_context(self, *args, **kwargs):
        result = await searxng_gateway.retrieve_web_context(*args, **kwargs)
        emit_event("web.tool", tool="web_search", status=result.status, result_count=len(result.results))
        return result

    async def read_url(self, *args, **kwargs):
        result = await page_reader.read_url(*args, **kwargs)
        emit_event("web.tool", tool="read_url", status="ok", result_count=1)
        return result

    def __getattr__(self, name):
        if name == "normalize_public_url":
            return url_policy.normalize_public_url
        module = page_reader if name in {"read_url", "WebReadRejectedError"} else (intent_policy if name in {"WebSearchPlan", "plan_web_search", "plan_web_search_with_context"} else searxng_gateway)
        return getattr(module, name)


web_gateway = WebWorkflowGateway()
