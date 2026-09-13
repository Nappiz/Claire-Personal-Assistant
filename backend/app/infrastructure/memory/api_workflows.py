"""Bind request-owned history/cancellation transactions, without orchestration."""
from app.domain.memory.contracts import TurnConflictError
from app.observability.operational_events import emit_event


class BoundMemoryWorkflows:
    TurnConflictError = TurnConflictError

    def __init__(self, workflows, uow=None):
        self.workflows, self.uow = workflows, uow

    def begin_turn(self, *args, **kwargs): return self.workflows.begin_turn(*args, **kwargs)
    def retrieve_context(self, *args, **kwargs):
        context = self.workflows.retrieve_context(*args, **kwargs)
        emit_event("memory.retrieved", candidate_ids=[item.message_id for item in context.qdrant_context if item.message_id])
        return context
    def save_interaction(self, **kwargs): return self.workflows.save_interaction(**kwargs)
    def mark_turn_status(self, *args, **kwargs): return self.workflows.mark_turn_status(*args, **kwargs)
    def process_memory_job(self, *args, **kwargs):
        result = self.workflows.process_memory_job(*args, **kwargs)
        if result:
            emit_event("memory.job", job_id=result.get("id"), job_state=result.get("status"))
        return result
    def process_conversation_summary(self, *args, **kwargs): return self.workflows.process_conversation_summary(*args, **kwargs)
    def generate_and_save_title(self, *args, **kwargs): return self.workflows.generate_and_save_title(*args, **kwargs)
    def record_internal_error(self, **kwargs): return self.workflows.record_internal_error(**kwargs)
    def list_memory_jobs(self, limit=50): return self.workflows.list_memory_jobs(limit)
    def retry_memory_job(self, job_id): return self.workflows.retry_memory_job(job_id)
    def set_source_messages_memory_status(self, message_ids, status): return self.workflows.set_source_messages_memory_status(message_ids, status)

    def cancel_memory_jobs_for_conversation(self, session_id):
        return self.workflows.cancel_memory_jobs_for_conversation(session_id, self.uow.db)

    def get_session_history(self, session_id, limit=200):
        return self.workflows.get_session_history(self.uow.db, session_id, limit=limit)

    def get_session_summary(self, session_id):
        return self.workflows.get_session_summary(self.uow.db, session_id)
