from app.application.dependencies import ChatDependencies
import uuid
from datetime import datetime, timezone
from app.application.errors import ApplicationError
def prepare_stream_session(request, dependencies: ChatDependencies):
    """Perform synchronous SQLAlchemy work outside the event-loop thread."""
    memory_service = dependencies.memory
    history = dependencies.history
    uow = dependencies.uow
    try:
        session_id = request.session_id
        should_generate_title = False
        project = None
        if request.project_id:
            project = uow.projects.get(request.project_id)
            if project is None:
                raise ApplicationError(status_code=404, detail="Project not found")
        if not session_id:
            conversation = uow.conversations.new(title='New Chat...', project_id=project.id if project else None)
            uow.commit()
            uow.refresh(conversation)
            session_id = conversation.id
            should_generate_title = True
        else:
            conversation = uow.conversations.get(session_id, active_only=True)
            if conversation is None:
                raise ApplicationError(status_code=404, detail="Session not found")
            if request.project_id and request.project_id != conversation.project_id:
                raise ApplicationError(
                    status_code=409,
                    detail="Session belongs to a different project",
                )
            project = conversation.project
            should_generate_title = (
                conversation.message_count == 0 and conversation.title == "New Chat..."
            )
            conversation.updated_at = datetime.now(timezone.utc)
            uow.commit()

        turn_id = request.turn_id or str(uuid.uuid4())
        turn_state = memory_service.begin_turn(session_id, request.message, turn_id)
        session_history = history.get_session_history(session_id, limit=200)
        session_summary = history.get_session_summary(session_id)
        return (
            session_id,
            should_generate_title,
            session_history,
            session_summary,
            conversation.project_id,
            project.name if project else None,
            turn_id,
            turn_state,
        )
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()
