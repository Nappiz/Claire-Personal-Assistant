from app.application.dependencies import ChatDependencies
import logging
import uuid
from app.application.errors import ApplicationError
from app.domain.diagnostics import InternalFeatureError, current_exception_log
async def stream_chat_endpoint(request, client_request, background_tasks, dependencies: ChatDependencies):
    """Stream an OpenAI-compatible chat completion to the browser as SSE."""
    memory_service = dependencies.memory
    llm_service = dependencies.llm
    run_in_threadpool = dependencies.threadpool
    set_usage_context = dependencies.set_usage_context
    reset_usage_context = dependencies.reset_usage_context
    _prepare_stream_session = dependencies.prepare_session
    _internal_error_payload = dependencies.internal_error_payload
    _upstream_error_payload = dependencies.provider_error_payload
    _is_llm_provider_error = dependencies.is_provider_error
    try:
        prepared_session = await run_in_threadpool(_prepare_stream_session, request)
        session_id, should_generate_title, session_history, session_summary = prepared_session[:4]
        active_project_id = prepared_session[4] if len(prepared_session) > 4 else None
        active_project_name = prepared_session[5] if len(prepared_session) > 5 else None
        turn_id = prepared_session[6] if len(prepared_session) > 6 else (request.turn_id or str(uuid.uuid4()))
        turn_state = prepared_session[7] if len(prepared_session) > 7 else {
            "turn_id": turn_id,
            "turn_sequence": None,
            "user_message_id": None,
            "completed": False,
        }
    except memory_service.TurnConflictError as exc:
        raise ApplicationError(status_code=409, detail=str(exc)) from exc
    except ApplicationError:
        raise
    except Exception as exc:
        internal_exc = InternalFeatureError(
            "chat_session",
            f"Sesi chat gagal disiapkan: {exc}",
            current_exception_log(),
        )

        async def failed_session_stream():
            yield await _internal_error_payload(
                    internal_exc,
                    request.session_id or "",
                    model=request.model,
                    provider=request.provider,
                )

        return failed_session_stream()

    async def finalize_internal_error(
        exc: InternalFeatureError,
        persistence: dict,
    ) -> dict:
        payload = await _internal_error_payload(
            exc,
            session_id,
            model=request.model,
            provider=request.provider,
        )
        error_details = dict(payload["error"])
        try:
            await run_in_threadpool(
                memory_service.record_internal_error,
                session_id=session_id,
                user_message=request.message,
                analysis=error_details["analysis"],
                error_details=error_details,
                user_message_id=persistence.get("user_message_id"),
                assistant_message_id=persistence.get("assistant_message_id"),
                memory_job_id=persistence.get("memory_job_id"),
                turn_id=turn_id,
                turn_sequence=turn_state.get("turn_sequence"),
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not persist internal error event for session %s", session_id
            )
        if should_generate_title:
            background_tasks.add_task(
                memory_service.generate_and_save_title,
                session_id=session_id,
                first_message=request.message,
            )
        return payload

    async def event_stream():
        reply_parts: list[str] = []
        usage: dict = {}
        persistence: dict = {}
        turn_finalized = False
        usage_token = None
        completion = {"response_status": "complete", "finish_reason": None}

        # Send the session immediately, before memory retrieval or the upstream
        # connection, so the UI can retain it across provider failover attempts.
        yield {"type": "session", "session_id": session_id, "turn_id": turn_id}

        try:
            usage_token = set_usage_context(conversation_id=session_id, turn_id=turn_id, job_id=None, job_attempt=None)
            if turn_state.get("completed"):
                cached_reply = str(turn_state.get("cached_reply") or "")
                if cached_reply:
                    yield {"type": "delta", "delta": cached_reply}
                yield {
                        "type": "done",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "usage": {},
                        "memory_status": {},
                        "web_search": {},
                        "response_status": turn_state.get("response_status", "complete"),
                        "finish_reason": turn_state.get("finish_reason"),
                    }
                turn_finalized = True
                return
            if await client_request.is_disconnected():
                await run_in_threadpool(
                    memory_service.mark_turn_status,
                    session_id,
                    turn_id,
                    "interrupted_turn",
                )
                return

            context = await run_in_threadpool(
                memory_service.retrieve_context,
                request.message,
                raise_on_error=False,
                project_id=active_project_id,
                session_history=session_history,
                session_summary=session_summary,
            )
            effective_project_id = context.project_scope.project_id or active_project_id
            effective_project_name = context.project_scope.project_name or active_project_name

            async for event in llm_service.generate_chat_response_stream(
                request.message,
                context,
                session_history,
                model=request.model,
                provider=request.provider,
                session_summary=session_summary,
                project_id=effective_project_id,
                project_name=effective_project_name,
            ):
                if await client_request.is_disconnected():
                    await run_in_threadpool(
                        memory_service.mark_turn_status,
                        session_id,
                        turn_id,
                        "interrupted_turn",
                    )
                    return

                if event["type"] == "web_search":
                    yield event
                    continue

                if event["type"] == "usage":
                    usage = event["usage"]
                    continue
                if event["type"] == "completion":
                    completion = {key: event[key] for key in ("response_status", "finish_reason")}
                    continue

                delta = event["delta"]
                reply_parts.append(delta)
                yield {"type": "delta", "delta": delta}

            reply = "".join(reply_parts)
            if not reply:
                raise RuntimeError("The upstream LLM returned an empty response")

            try:
                persistence = await run_in_threadpool(
                    memory_service.save_interaction,
                    session_id=session_id,
                    user_message=request.message,
                    ai_response=reply,
                    usage=usage,
                    context=context,
                    session_history=session_history,
                    session_summary=session_summary,
                    llm_provider=request.provider or "google",
                    llm_model=request.model or llm_service.DEFAULT_MODEL_NAME,
                    report_errors=False,
                    project_id=effective_project_id,
                    project_name=effective_project_name,
                    turn_id=turn_id,
                    turn_sequence=turn_state["turn_sequence"],
                    user_message_id=turn_state["user_message_id"],
                    process_memory=False,
                    **completion,
                )
            except Exception as exc:
                logging.getLogger(__name__).exception(
                    "Chat persistence failed for session %s", session_id
                )
                raise InternalFeatureError.from_active_exception(
                    "chat_persistence",
                    f"Penyimpanan interaksi gagal: {exc}",
                ) from exc

            if persistence.get("memory_job_id"):
                background_tasks.add_task(
                    memory_service.process_memory_job,
                    persistence["memory_job_id"],
                )
            background_tasks.add_task(
                memory_service.process_conversation_summary,
                session_id,
            )

            if should_generate_title:
                background_tasks.add_task(
                    memory_service.generate_and_save_title,
                    session_id=session_id,
                    first_message=request.message,
                )

            yield {
                    "type": "done",
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "usage": usage,
                    "memory_status": context.retrieval_status.model_dump(),
                    "web_search": context.web_context.model_dump(),
                    **completion,
                }
            turn_finalized = True
        except InternalFeatureError as exc:
            logging.getLogger(__name__).exception(
                "Internal chat feature failed for session %s (%s)",
                session_id,
                exc.operation,
            )
            yield await finalize_internal_error(exc, persistence)
            turn_finalized = True
        except Exception as exc:
            if _is_llm_provider_error(exc):
                logging.getLogger(__name__).exception(
                    "Streaming LLM request failed for session %s", session_id
                )
                await run_in_threadpool(
                    memory_service.mark_turn_status,
                    session_id,
                    turn_id,
                    "interrupted_turn",
                    {"error": type(exc).__name__},
                )
                payload = _upstream_error_payload(exc, session_id)
                payload["turn_id"] = turn_id
                yield payload
                turn_finalized = True
            else:
                logging.getLogger(__name__).exception(
                    "Unexpected internal chat failure for session %s", session_id
                )
                internal_exc = InternalFeatureError(
                    "chat_pipeline",
                    f"Pipeline chat mengalami error internal: {exc}",
                    current_exception_log(),
                )
                yield await finalize_internal_error(internal_exc, persistence)
                turn_finalized = True
        finally:
            if not turn_finalized:
                try:
                    await run_in_threadpool(
                        memory_service.mark_turn_status,
                        session_id,
                        turn_id,
                        "interrupted_turn",
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Could not release interrupted turn %s", turn_id
                    )
            if usage_token is not None:
                reset_usage_context(usage_token)

    return event_stream()
