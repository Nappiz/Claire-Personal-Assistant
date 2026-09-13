"""Existing web implementation behind a workflow boundary; no algorithm changes."""
from services import web_reader_service, web_search_service


class WebWorkflowGateway:
    def __getattr__(self, name):
        module = web_reader_service if name in {"read_url", "WebReadRejectedError"} else web_search_service
        return getattr(module, name)


web_gateway = WebWorkflowGateway()
