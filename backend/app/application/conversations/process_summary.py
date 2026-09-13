from __future__ import annotations
import logging
import traceback
import time
import uuid
import re
import concurrent.futures
from datetime import datetime, timedelta, timezone
from typing import Any
from schemas.chat_sch import MemoryContext, ProjectScopeContext, RetrievalStatus, QueryResolution
from app.domain.llm.contracts import MemoryLLMUnavailableError, ERROR_FALLBACK_MSG
from app.domain.memory.contracts import TurnConflictError, _MEMORY_RECALL_RE, _HISTORICAL_RE, _SEARCH_STOPWORDS, _VAGUE_PROJECT_REFERENCE_RE, _MEMORY_RETRY_BASE_SECONDS, _MEMORY_RETRY_MAX_SECONDS, _MEMORY_JOB_LEASE_SECONDS
from app.domain.diagnostics import InternalFeatureError, current_exception_log, redact_diagnostic_log
logger = logging.getLogger("services.memory_service")

class ProcessSummary:
    def process_conversation_summary(self, session_id: str) -> dict:
        """Fold old completed turns with an optimistic checkpoint; stale writers lose."""
    
        db = self.persistence.open()
        try:
            conversation = (
                db.process_conversation_summary_conversation(session_id)
            )
            if conversation is None:
                return {"status": "missing"}
            version = int(conversation.summary_version or 0)
            checkpoint = int(conversation.summary_through_sequence or 0)
            expected_next_sequence = int(conversation.next_turn_sequence or 1)
            current_summary = str(conversation.summary or "")
            rows = (
                db.process_conversation_summary_rows(checkpoint, session_id)
            )
        finally:
            db.close()
    
        if len(rows) <= 30:
            db = self.persistence.open()
            try:
                db.process_conversation_summary_update(expected_next_sequence, session_id, version)
                db.commit()
            finally:
                db.close()
            return {"status": "not_due", "folded": 0}
    
        keep_from_sequence = int(rows[-30].turn_sequence or 0)
        fold_candidates = [row for row in rows if int(row.turn_sequence or 0) < keep_from_sequence]
        if not fold_candidates:
            return {"status": "not_due", "folded": 0}
        fold_rows: list[db.new_message] = []
        estimated_tokens = max(1, len(current_summary) // 3)
        for sequence in sorted({int(row.turn_sequence or 0) for row in fold_candidates}):
            group = [row for row in fold_candidates if int(row.turn_sequence or 0) == sequence]
            group_cost = sum(max(1, len(row.content or "") // 3) + 8 for row in group)
            if fold_rows and estimated_tokens + group_cost > 16_000:
                break
            fold_rows.extend(group)
            estimated_tokens += group_cost
        fold_through = max(int(row.turn_sequence or 0) for row in fold_rows)
        messages = [{"role": row.role, "content": row.content} for row in fold_rows]
        with self.usage_context(conversation_id=session_id, turn_id=None, job_id=None, job_attempt=None):
            updated_summary = self.generate_session_summary(current_summary, messages)
    
        db = self.persistence.open()
        try:
            result = db.process_conversation_summary_result(checkpoint, expected_next_sequence, fold_through, session_id, updated_summary, version)
            db.commit()
            return {"status": "updated" if result == 1 else "stale", "folded": len(fold_rows)}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def process_due_summaries(self, limit: int = 20) -> list[dict]:
    
        db = self.persistence.open()
        try:
            ids = [
                row[0]
                for row in db.process_due_summaries_ids(limit)
            ]
        finally:
            db.close()
        results = []
        for session_id in ids:
            try:
                results.append(self.process_conversation_summary(session_id))
            except Exception:
                logger.exception("Conversation summary retry failed for %s", session_id)
        return results
