from app.application.memory.resolve_project_scope import ResolveProjectScope
from app.application.memory.retrieve_context import RetrieveContext
from app.application.conversations.read_history import ReadHistory
from app.application.conversations.begin_turn import BeginTurn
from app.application.conversations.complete_turn import CompleteTurn
from app.application.conversations.persist_interaction import PersistInteraction
from app.application.memory.outbox_snapshots import OutboxSnapshots
from app.application.memory.outbox_leases import OutboxLeases
from app.application.memory.process_outbox_job import ProcessOutboxJob
from app.application.memory.retry_due_jobs import RetryDueJobs
from app.application.conversations.cancel_conversation_jobs import CancelConversationJobs
from app.application.conversations.process_summary import ProcessSummary
from app.application.conversations.record_internal_error import RecordInternalError
from app.application.memory.reindex_vectors import ReindexVectors
from app.application.conversations.save_title import SaveTitle
from app.domain.memory.contracts import TurnConflictError
from app.domain.memory.turn_policy import TurnPolicy


class MemoryWorkflows(ResolveProjectScope, RetrieveContext, ReadHistory, BeginTurn, CompleteTurn, PersistInteraction, OutboxSnapshots, OutboxLeases, ProcessOutboxJob, RetryDueJobs, CancelConversationJobs, ProcessSummary, RecordInternalError, ReindexVectors, SaveTitle):
    """Composition only; each workflow has its own module and injectable ports."""
    TurnConflictError = TurnConflictError

    def __init__(self, *, config, persistence, graph, vector, llm, retrieval_executor,
                 scope, retrieval, assertion, outbox, usage_context, turn=None):
        self.config, self.persistence, self.graph, self.vector = config, persistence, graph, vector
        self.llm, self.retrieval_executor = llm, retrieval_executor
        self.turn = turn if turn is not None else TurnPolicy()
        self.scope, self.retrieval, self.assertion, self.outbox = scope, retrieval, assertion, outbox
        self.references, self.usage_context = llm.references, usage_context
        self.route_memory_query, self.extract_knowledge = llm.route_memory_query, llm.extract_knowledge
        self.search_memory, self.search_project_memory_candidates = vector.search_memory, vector.search_project_memory_candidates
        self.save_memory, self.reconcile_memory = vector.save_memory, vector.reconcile_memory

    @property
    def generate_session_summary(self):
        return self.llm.generate_session_summary

    @property
    def generate_session_title(self):
        return self.llm.generate_session_title
