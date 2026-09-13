"""Stream a planner's visible answer while retaining its tool replay payload."""
import asyncio

from app.domain.llm.tool_contracts import WEB_TOOL_DEFINITIONS


async def stream_planning_response(workflow, state, result):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + state.planning_timeout
    async with asyncio.timeout(state.planning_timeout):
        stream, invocation_id = await workflow.gateway.tracked_async_completion(
            state.client, purpose="chat_planning", provider=state.provider,
            model=state.model_name, messages=state.llm_messages,
            temperature=0.0, max_tokens=workflow.config.CHAT_OUTPUT_MAX_TOKENS,
            tools=WEB_TOOL_DEFINITIONS, tool_choice="auto",
            stream=True, stream_options={"include_usage": True},
        )
    workflow.responses.add_usage(state.total_usage, None, invocation_id)
    last_usage = None
    try:
        async with stream:
            iterator = aiter(stream)
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError("LLM web-tool planning deadline exceeded")
                try:
                    # Do not keep an asyncio.timeout context across a yield:
                    # an SSE consumer may resume this generator in another task.
                    chunk = await asyncio.wait_for(anext(iterator), timeout=remaining)
                except StopAsyncIteration:
                    break
                if getattr(chunk, "usage", None) is not None:
                    last_usage = chunk.usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]
                text = workflow.responses.stream_delta_text(getattr(choice, "delta", None))
                result.add_choice(choice, text, workflow.responses.finish_reason_text(
                    getattr(choice, "finish_reason", None)))
                if text and not result.calls and not result.refusal:
                    state.planning_text_emitted = True
                    yield {"type": "delta", "delta": text}
    finally:
        # Usage is cumulative per invocation, including usage-only tail chunks.
        workflow.responses.add_usage(state.total_usage, last_usage)
