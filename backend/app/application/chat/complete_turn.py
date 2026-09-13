from app.application.dependencies import ChatDependencies
import uuid
from schemas.chat_sch import ChatResponse
from app.application.errors import ApplicationError
async def chat_endpoint(request, background_tasks, dependencies: ChatDependencies):
    """Run one durable, idempotent chat turn."""
    uow = dependencies.uow
    memory_service = dependencies.memory
    llm_service = dependencies.llm
    history = dependencies.history
    run_in_threadpool = dependencies.threadpool
    set_usage_context = dependencies.set_usage_context
    reset_usage_context = dependencies.reset_usage_context
    session_id = request.session_id
    is_new_session = False
    if not session_id:
        project = uow.projects.get(request.project_id) if request.project_id else None
        if request.project_id and project is None:
            raise ApplicationError(status_code=404, detail="Project not found")
        conversation = uow.conversations.new(title='New Chat...', project_id=project.id if project else None)
        uow.commit()
        uow.refresh(conversation)
        session_id = conversation.id
        is_new_session = True
    else:
        conversation = (
            uow.conversations.get(session_id, active_only=True)
        )
        if conversation is None:
            raise ApplicationError(status_code=404, detail="Session not found")
        if request.project_id and request.project_id != conversation.project_id:
            raise ApplicationError(status_code=409, detail="Session belongs to a different project")
        project = conversation.project

    turn_id = request.turn_id or str(uuid.uuid4())
    try:
        turn_state = await run_in_threadpool(
            memory_service.begin_turn, session_id, request.message, turn_id
        )
    except memory_service.TurnConflictError as exc:
        raise ApplicationError(status_code=409, detail=str(exc)) from exc

    if turn_state.get("completed"):
        return ChatResponse(
            reply=str(turn_state["cached_reply"]),
            session_id=session_id,
            turn_id=turn_id,
            context_used={},
            response_status=turn_state.get("response_status", "complete"),
            finish_reason=turn_state.get("finish_reason"),
        )

    session_history = history.get_session_history(session_id, limit=200)
    session_summary = history.get_session_summary(session_id)
    active_project_id = conversation.project_id
    active_project_name = project.name if project else None
    usage_token = set_usage_context(conversation_id=session_id, turn_id=turn_id, job_id=None, job_attempt=None)
    try:
        context = await run_in_threadpool(
            memory_service.retrieve_context,
            request.message,
            project_id=active_project_id,
            session_history=session_history,
            session_summary=session_summary,
        )
        effective_project_id = context.project_scope.project_id or active_project_id
        effective_project_name = context.project_scope.project_name or active_project_name
        reply_parts: list[str] = []
        usage: dict = {}
        completion = {"response_status": "complete", "finish_reason": None}
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
            if event["type"] == "delta":
                reply_parts.append(event["delta"])
            elif event["type"] == "usage":
                usage = event["usage"]
            elif event["type"] == "completion":
                completion = {key: event[key] for key in ("response_status", "finish_reason")}
        reply = "".join(reply_parts)
        if not reply:
            raise RuntimeError("The upstream LLM returned an empty response")

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
            project_id=effective_project_id,
            project_name=effective_project_name,
            turn_id=turn_id,
            turn_sequence=turn_state["turn_sequence"],
            user_message_id=turn_state["user_message_id"],
            process_memory=False,
            **completion,
        )
    except Exception as exc:
        await run_in_threadpool(
            memory_service.mark_turn_status,
            session_id,
            turn_id,
            "failed_turn",
            {"error": type(exc).__name__},
        )
        raise

    finally:
        reset_usage_context(usage_token)

    if persistence.get("memory_job_id"):
        background_tasks.add_task(memory_service.process_memory_job, persistence["memory_job_id"])
    background_tasks.add_task(memory_service.process_conversation_summary, session_id)
    if is_new_session:
        background_tasks.add_task(
            memory_service.generate_and_save_title,
            session_id=session_id,
            first_message=request.message,
        )
    return ChatResponse(reply=reply, session_id=session_id, turn_id=turn_id, context_used=context, **completion)
