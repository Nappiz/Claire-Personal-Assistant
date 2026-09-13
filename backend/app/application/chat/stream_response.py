from __future__ import annotations
from app.application.chat.execute_web_tool_loop import ToolLoopState
import logging
import re
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any
from schemas.chat_sch import MemoryContext, WebPageContent
from app.domain.llm.contracts import DEFAULT_MODEL_NAME
from app.domain.llm.tool_contracts import WEB_TOOL_INSTRUCTIONS
logger = logging.getLogger("services.llm_service")

class StreamResponse:
    async def generate_chat_response_stream(self,
        user_message: str,
        memory_context: MemoryContext,
        session_history: list | None = None,
        model: str | None = None,
        provider: str | None = None,
        session_summary: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
    ) -> AsyncIterator[dict]:
        """Run bounded web tools, then stream the final answer from the same LLM thread."""
        web_reader_service = web_search_service = self.web
        clarification = self.references.reference_clarification(memory_context)
        if clarification:
            yield {"type": "delta", "delta": clarification}
            yield {"type": "completion", "response_status": "complete", "finish_reason": "stop"}
            return

        logger.info("Streaming response from %s (%s)...", provider, model)
        model_name = model or DEFAULT_MODEL_NAME
        llm_messages = self.prompts.build_chat_messages(
            user_message,
            memory_context,
            session_history,
            session_summary,
            project_id,
            project_name,
        )
        llm_messages[0]["content"] += WEB_TOOL_INSTRUCTIONS
        web_tools_allowed = self.tools.web_tools_allowed_for_turn(user_message, memory_context)
        if not web_tools_allowed:
            llm_messages[0]["content"] += """

PROJECT MEMORY OVERRIDE:
- Turn ini adalah penelusuran konteks internal project. Gunakan hanya riwayat, vector memory, knowledge graph, dan memori global yang sudah diberikan.
- Jangan melakukan web search atau mengklaim mencari internet. Jika data internal belum cukup, tanyakan detail yang kurang secara singkat; jangan menggantinya dengan tebakan atau informasi web.
"""
            logger.info(
                "Web tools disabled for project-memory turn (project_id=%s, resolution=%s)",
                memory_context.project_scope.project_id,
                memory_context.project_scope.resolution,
            )
        base_message_count = len(llm_messages)

        # Provider settings currently live in synchronous SQLAlchemy. Resolve them
        # in the worker pool so opening a stream never blocks the event loop.
        api_key, base_url = await self.threadpool(self.gateway.get_llm_connection, provider)
        client = self.gateway.create_async_llm_client(api_key, base_url)
        total_usage: dict[str, int] = {}
        web_context = memory_context.web_context
        search_performed = web_context.status != "not_needed"
        allowed_urls = {result.url for result in web_context.results}
        pages: list[WebPageContent] = list(web_context.pages)
        simple_social_turn = bool(re.fullmatch(
            r"\s*(?:hi|hello|halo|hai|hey|pagi|siang|sore|malam|"
            r"selamat\s+(?:pagi|siang|sore|malam)|makasih|terima\s+kasih|"
            r"thanks|thank\s+you|good\s+(?:morning|afternoon|evening|night))"
            r"(?:\s+(?:chat|claire|kamu))?[\s!.,]*", user_message, flags=re.IGNORECASE
        ))
        max_rounds = (
            max(1, min(int(self.config.WEB_TOOL_MAX_ROUNDS), 4))
            if web_tools_allowed and not simple_social_turn
            else 0
        )
        max_read_urls = max(1, min(int(self.config.WEB_READ_MAX_URLS), 2))
        read_cache = {page.url: {"ok": True, **page.model_dump()} for page in pages}
        attempted_urls = set(read_cache)
        direct_answer: str | None = None
        direct_finish_reason: str | None = None
        planning_timeout = max(
            2.0,
            min(float(self.config.WEB_TOOL_PLANNING_TIMEOUT_SECONDS), 30.0),
        )

        try:
            state = ToolLoopState(client=client, provider=provider, model_name=model_name, user_message=user_message, session_history=session_history, memory_context=memory_context, llm_messages=llm_messages, total_usage=total_usage, web_context=web_context, search_performed=search_performed, allowed_urls=allowed_urls, pages=pages, max_rounds=max_rounds, max_read_urls=max_read_urls, read_cache=read_cache, attempted_urls=attempted_urls, direct_answer=direct_answer, direct_finish_reason=direct_finish_reason, planning_timeout=planning_timeout, base_message_count=base_message_count, web_tools_allowed=web_tools_allowed)
            async with aclosing(self.execute_web_tool_loop(state)) as planning:
                async for event in planning:
                    yield event
            web_context, search_performed = state.web_context, state.search_performed
            direct_answer, direct_finish_reason = state.direct_answer, state.direct_finish_reason

            if search_performed:
                yield {
                    "type": "web_search",
                    "phase": "complete",
                    "status": web_context.status,
                    "query": web_context.query or user_message[:300],
                    "results": [
                        {
                            "title": result.title,
                            "url": result.url,
                            "engine": result.engine,
                        }
                        for result in web_context.results
                    ],
                    "pages": [
                        {"title": page.title, "url": page.url}
                        for page in web_context.pages
                    ],
                }

                # The planning phase is over. Some OpenAI-compatible Gemini models
                # otherwise attempt another implicit tool call in the final request,
                # which produces a successful HTTP response but no visible text.
                llm_messages[0]["content"] += """

FINAL RESPONSE PHASE:
- Fase penggunaan tool sudah ditutup. Jangan memanggil web_search, read_url, atau tool lain lagi.
- Berikan jawaban final kepada user sekarang berdasarkan hasil tool yang sudah ada.
- Jika bukti tidak memadai, nyatakan batasnya secara jujur; jangan menebak.
"""

            if direct_answer is not None:
                # The planner's provider deltas were already forwarded above.
                if total_usage:
                    yield {"type": "usage", "usage": dict(total_usage)}
                yield self.responses.completion_outcome({"finish_reasons": [direct_finish_reason] if direct_finish_reason else []})
                return

            usage_emitted = False
            answer_text_emitted = False

            async def stream_final_attempt(
                messages: list[dict[str, Any]],
                diagnostics: dict[str, Any],
                purpose: str = "chat_answer",
            ) -> AsyncIterator[dict]:
                nonlocal usage_emitted, answer_text_emitted
                stream, invocation_id = await self.gateway.tracked_async_completion(
                    client, purpose=purpose, provider=provider,
                    model=model_name,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=self.config.CHAT_OUTPUT_MAX_TOKENS,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                last_usage = {}
                self.responses.add_usage(total_usage, None, invocation_id)
                async with stream:
                    async for chunk in stream:
                        usage = getattr(chunk, "usage", None)
                        if usage is not None:
                            current_usage = self.responses.usage_values(usage)
                            for key, value in current_usage.items():
                                total_usage[key] = total_usage.get(key, 0) + value - last_usage.get(key, 0)
                            last_usage = current_usage
                            yield {
                                "type": "usage",
                                "usage": dict(total_usage),
                            }
                            usage_emitted = True

                        for choice in getattr(chunk, "choices", None) or []:
                            self.responses.record_stream_diagnostics(choice, diagnostics)
                            content = self.responses.stream_delta_text(getattr(choice, "delta", None))
                            if content:
                                # Provider chunk boundaries are arbitrary. A chunk that is
                                # only whitespace may carry a word separator, Markdown
                                # newline, or code indentation and must survive verbatim.
                                if content.strip():
                                    answer_text_emitted = True
                                yield {"type": "delta", "delta": content}

            first_diagnostics: dict[str, Any] = {
                "finish_reasons": [],
                "tool_calls": [],
                "refusal": "",
            }
            async with aclosing(stream_final_attempt(llm_messages, first_diagnostics)) as attempt:
                async for event in attempt:
                    yield event
            final_diagnostics = first_diagnostics

            if not answer_text_emitted:
                logger.warning(
                    "Final LLM stream returned no visible text; finish_reasons=%s, "
                    "tool_calls=%s, refusal=%s. Retrying once with clean tool history.",
                    first_diagnostics["finish_reasons"],
                    first_diagnostics["tool_calls"],
                    bool(first_diagnostics["refusal"]),
                )
                recovery_messages = self.prompts.build_final_recovery_messages(
                    llm_messages,
                    base_message_count,
                    web_context,
                )
                recovery_diagnostics: dict[str, Any] = {
                    "finish_reasons": [],
                    "tool_calls": [],
                    "refusal": "",
                }
                async with aclosing(stream_final_attempt(
                    recovery_messages,
                    recovery_diagnostics,
                    purpose="chat_recovery",
                )) as attempt:
                    async for event in attempt:
                        yield event

                if not answer_text_emitted:
                    logger.error(
                        "Final LLM recovery stream also returned no visible text; "
                        "finish_reasons=%s, tool_calls=%s, refusal=%s",
                        recovery_diagnostics["finish_reasons"],
                        recovery_diagnostics["tool_calls"],
                        bool(recovery_diagnostics["refusal"]),
                    )
                final_diagnostics = recovery_diagnostics

            if total_usage and not usage_emitted:
                yield {"type": "usage", "usage": dict(total_usage)}
            yield self.responses.completion_outcome(final_diagnostics)
        finally:
            await client.close()
