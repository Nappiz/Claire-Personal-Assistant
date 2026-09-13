from app.application.chat.execute_web_tool_loop import ExecuteWebToolLoop
from app.application.chat.generate_response import GenerateResponse
from app.application.chat.stream_response import StreamResponse
from app.application.memory.extract_knowledge import ExtractKnowledge
from app.application.memory.route_memory_query import RouteMemoryQuery
from app.application.conversations.generate_title import GenerateTitle
from app.application.conversations.generate_summary import GenerateSummary
from app.application.diagnostics.analyze_error import AnalyzeError
from app.domain.llm.contracts import DEFAULT_MODEL_NAME
from app.ports.completion_gateway import CompletionGateway


class LLMWorkflows(ExecuteWebToolLoop, GenerateResponse, StreamResponse, ExtractKnowledge, RouteMemoryQuery, GenerateTitle, GenerateSummary, AnalyzeError):
    """Composition of bounded workflows, with injectable provider-neutral ports."""
    DEFAULT_MODEL_NAME = DEFAULT_MODEL_NAME

    def __init__(self, *, gateway: CompletionGateway, config, web, prompts,
                 references, extraction, responses, tools, ground_locations, threadpool):
        self.gateway, self.config, self.web = gateway, config, web
        self.prompts, self.references, self.extraction = prompts, references, extraction
        self.responses, self.tools = responses, tools
        self.ground_locations, self.threadpool = ground_locations, threadpool
