from sqlalchemy import func
from models.conversation import Conversation
from models.message import Message
from models.llm_usage import LLMUsageLog
from models.ai_invocation import AIInvocation


class SQLAlchemyUsageRepository:
    def __init__(self, db):
        self.db = db

    def stats(self):
        db = self.db
        tokens = db.query(func.sum(LLMUsageLog.prompt_tokens + LLMUsageLog.completion_tokens)).scalar() or 0
        tokens += db.query(func.sum(AIInvocation.total_tokens)).scalar() or 0
        return {
            "sessions": db.query(Conversation).count(),
            "messages": db.query(Message).count(),
            "tokens": tokens,
            "ai_invocations": db.query(AIInvocation).count(),
            "ai_invocations_unknown_usage": db.query(AIInvocation).filter(AIInvocation.total_tokens.is_(None)).count(),
        }
