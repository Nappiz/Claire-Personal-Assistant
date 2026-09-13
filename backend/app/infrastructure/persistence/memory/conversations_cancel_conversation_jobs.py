from models.memory_outbox import MemoryOutbox

class CancelConversationJobsQueries:
    def cancel_memory_jobs_for_conversation_result(self, session_id):
        return (self.db.query(MemoryOutbox)
        .filter(
            MemoryOutbox.conversation_id == session_id,
            MemoryOutbox.status.in_(["pending", "processing", "failed"]),
        )
        .update(
            {
                MemoryOutbox.status: "cancelled",
                MemoryOutbox.next_retry_at: None,
                MemoryOutbox.last_error: "Source conversation deleted",
                MemoryOutbox.lease_token: None,
                MemoryOutbox.lease_expires_at: None,
            },
            synchronize_session=False,
        ))
