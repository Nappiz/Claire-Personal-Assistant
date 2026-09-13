from app.domain.memory.turn_policy import TurnPolicy
from app.application.memory.resolve_project_scope import ResolveProjectScope
from app.application.memory.retrieve_context import RetrieveContext
from app.application.conversations.read_history import ReadHistory
from app.application.conversations.begin_turn import BeginTurn
from app.application.conversations.complete_turn import CompleteTurn
from app.application.conversations.persist_interaction import PersistInteraction
from app.domain.memory.contracts import TurnConflictError


class MemoryWorkflows(ResolveProjectScope, RetrieveContext, ReadHistory, BeginTurn, CompleteTurn, PersistInteraction):
    """Composition only; each workflow has its own module and injectable ports."""
    TurnConflictError = TurnConflictError

    def __init__(self, *, config, persistence, graph, vector, llm, retrieval_executor,
                 scope, retrieval, assertion, outbox, usage_context, turn=None):
        self.config, self.persistence, self.graph, self.vector = config, persistence, graph, vector
        self.turn = turn if turn is not None else TurnPolicy()
        self.llm, self.retrieval_executor = llm, retrieval_executor
        self.scope, self.retrieval, self.assertion, self.outbox = scope, retrieval, assertion, outbox
        self.references, self.usage_context = llm.references, usage_context
        self.route_memory_query, self.extract_knowledge = llm.route_memory_query, llm.extract_knowledge
        self.search_memory, self.search_project_memory_candidates = vector.search_memory, vector.search_project_memory_candidates
        self.save_memory, self.reconcile_memory = vector.save_memory, vector.reconcile_memory
        self.generate_session_summary, self.generate_session_title = llm.generate_session_summary, llm.generate_session_title
