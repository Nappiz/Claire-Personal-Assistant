from app.application.dependencies import ResourceDependencies
import logging
from datetime import datetime, timezone
from app.application.errors import ApplicationError
def get_sessions(dependencies: ResourceDependencies):
    """Mendapatkan daftar semua sesi obrolan (terbaru di atas)"""
    uow = dependencies.uow
    convs = (
        uow.conversations.list()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "is_pinned": bool(c.is_pinned),
            "pinned_at": c.pinned_at,
            "project_id": c.project_id,
            "created_at": c.created_at,
            "updated_at": c.updated_at
        } for c in convs
    ]

def set_session_pin(session_id, request, dependencies: ResourceDependencies):
    """Pin or unpin a conversation in the history sidebar."""
    uow = dependencies.uow
    conversation = uow.conversations.get(session_id)
    if conversation is None:
        raise ApplicationError(status_code=404, detail="Session not found")

    conversation.is_pinned = request.is_pinned
    conversation.pinned_at = datetime.now(timezone.utc) if request.is_pinned else None
    uow.commit()
    uow.refresh(conversation)
    return {
        "id": conversation.id,
        "is_pinned": bool(conversation.is_pinned),
        "pinned_at": conversation.pinned_at,
    }

def get_history(session_id, dependencies: ResourceDependencies):
    """Mendapatkan riwayat obrolan lengkap dari sesi tertentu"""
    uow = dependencies.uow
    active = uow.conversations.get(session_id, active_only=True)
    if active is None:
        raise ApplicationError(status_code=404, detail="Session not found")
    messages = uow.messages.history(session_id)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "message_type": m.message_type,
            "internal_error": m.error_details,
            "created_at": m.created_at,
            "response_status": m.response_status,
            "finish_reason": m.finish_reason,
        } for m in messages
    ]

def delete_session(session_id, dependencies: ResourceDependencies):
    """Delete a session and memory whose only evidence is that session."""
    uow = dependencies.uow
    memory_service = dependencies.memory
    neo4j_client = dependencies.graph
    delete_memory_by_session = dependencies.vector.delete_memory_by_session

    # 1. Hapus dari SQLite (UI History)
    conv = uow.conversations.get(session_id)
    if not conv:
        raise ApplicationError(status_code=404, detail="Session not found")

    source_message_ids = [message.id for message in conv.messages]

    # Persist cancellation before touching external stores so a background
    # worker cannot recreate graph/vector memory during session deletion.
    conv.deleted_at = conv.deleted_at or datetime.now(timezone.utc)
    conv.active_turn_id = None
    conv.active_turn_expires_at = None
    conv.is_pinned = False
    conv.pinned_at = None
    memory_service.cancel_memory_jobs_for_conversation(session_id)
    uow.commit()

    try:
        # External deletion is intentionally completed before SQLite history is
        # removed. If it fails, the user can retry and provenance remains
        # available instead of silently becoming dangling evidence.
        graph_cleanup = neo4j_client.remove_conversation_provenance(
            session_id,
            source_message_ids,
        )
        # Run vector deletion last. A worker which was already inside an
        # in-flight upsert when cancellation was committed is then still
        # covered by this final session-wide delete.
        delete_memory_by_session(session_id)
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to fully delete session %s", session_id)
        raise ApplicationError(
            status_code=502,
            detail="Session is tombstoned, but external memory cleanup failed and must be retried",
        ) from exc

    uow.messages.delete_for_conversation(session_id)
    uow.jobs.delete_for_conversation(session_id)
    conv.title = "Deleted session"
    conv.summary = None
    conv.summary_pending = False
    conv.project_id = None
    uow.commit()

    return {"message": "Session and derived memory deleted successfully", "graph_cleanup": graph_cleanup}
