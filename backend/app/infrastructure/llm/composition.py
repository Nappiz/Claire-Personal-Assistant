from fastapi.concurrency import run_in_threadpool
from configs.settings import settings
from app.domain.llm.prompt_policy import ChatPromptPolicy
from app.domain.llm.memory_query_policy import MemoryQueryPolicy
from app.domain.llm.extraction_policy import ExtractionPolicy
from app.domain.llm.response_policy import ResponsePolicy
from app.domain.llm.web_tool_policy import WebToolPolicy
from app.domain.llm.location_grounding import ground_locations
from app.application.llm.workflows import LLMWorkflows
from app.infrastructure.llm.openai_gateway import OpenAICompletionGateway
from app.infrastructure.web.workflow_gateway import web_gateway

gateway = OpenAICompletionGateway(settings)
prompts = ChatPromptPolicy(settings)
references = MemoryQueryPolicy(settings)
prompts.references = references
extraction = ExtractionPolicy(settings, prompts=prompts)
prompts.extraction = extraction
responses = ResponsePolicy(settings)
tools = WebToolPolicy(settings, web=web_gateway)
llm_workflows = LLMWorkflows(gateway=gateway, config=settings, web=web_gateway,
    prompts=prompts, references=references, extraction=extraction, responses=responses,
    tools=tools, ground_locations=ground_locations, threadpool=run_in_threadpool)
