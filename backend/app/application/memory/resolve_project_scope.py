from __future__ import annotations
import logging
from schemas.chat_sch import ProjectScopeContext
from app.domain.memory.contracts import VAGUE_PROJECT_REFERENCE_RE
logger = logging.getLogger("services.memory_service")

class ResolveProjectScope:
    def resolve_project_scope(self, 
        user_message: str,
        *,
        session_project_id: str | None = None,
        session_history: list[dict] | None = None,
    ) -> ProjectScopeContext:
        """Resolve project references without exposing memories from every project."""
    
        db = self.persistence.open()
        try:
            projects = db.resolve_project_scope_projects()
            project_rows = [(str(project.id), str(project.name)) for project in projects]
        finally:
            db.close()
    
        if session_project_id:
            match = next((item for item in project_rows if item[0] == session_project_id), None)
            return ProjectScopeContext(
                status="resolved",
                project_id=session_project_id,
                project_name=match[1] if match else session_project_id,
                resolution="session",
            )
    
        named_matches = [item for item in project_rows if self.scope.mentions_project_name(user_message, item[1])]
        if len(named_matches) == 1:
            return ProjectScopeContext(
                status="resolved",
                project_id=named_matches[0][0],
                project_name=named_matches[0][1],
                resolution="message",
            )
        if len(named_matches) > 1:
            return ProjectScopeContext(
                status="ambiguous",
                candidates=[name for _, name in named_matches],
            )
    
        # A bare use of "project" often names a public concept (for example,
        # project management). Only possessive/deictic wording is a reference to
        # one of the user's stored projects; explicit project names were handled
        # above.
        has_owned_project_reference = bool(VAGUE_PROJECT_REFERENCE_RE.search(user_message))
        if not has_owned_project_reference:
            return ProjectScopeContext()
    
        for message in reversed(list(session_history or [])[-12:]):
            content = str(message.get("content") or "") if isinstance(message, dict) else ""
            history_matches = [item for item in project_rows if self.scope.mentions_project_name(content, item[1])]
            if len(history_matches) == 1:
                return ProjectScopeContext(
                    status="resolved",
                    project_id=history_matches[0][0],
                    project_name=history_matches[0][1],
                    resolution="history",
                )
    
        if len(project_rows) == 1 and VAGUE_PROJECT_REFERENCE_RE.search(user_message):
            return ProjectScopeContext(
                status="resolved",
                project_id=project_rows[0][0],
                project_name=project_rows[0][1],
                resolution="single",
            )
    
        if project_rows:
            try:
                evidence = self.search_project_memory_candidates(user_message, limit=12)
            except Exception:
                logger.exception("Project-scope semantic resolution failed")
                evidence = []
            scores: dict[str, float] = {}
            for item in evidence:
                candidate_id = str(item.get("project_id") or "")
                if candidate_id not in {project_id for project_id, _ in project_rows}:
                    continue
                score = float(item.get("score") or 0.0)
                scores[candidate_id] = max(scores.get(candidate_id, -1.0), score)
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    
            resolution_min_score = min(
                max(float(self.config.MEMORY_SEARCH_SCORE_THRESHOLD) + 0.03, 0.78),
                0.90,
            )
            if (
                ranked
                and ranked[0][1] >= resolution_min_score
                and (len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= 0.05)
            ):
                resolved_id = ranked[0][0]
                resolved_name = next(name for project_id, name in project_rows if project_id == resolved_id)
                return ProjectScopeContext(
                    status="resolved",
                    project_id=resolved_id,
                    project_name=resolved_name,
                    resolution="semantic",
                )
    
        return ProjectScopeContext(
            status="ambiguous",
            candidates=[name for _, name in project_rows[:8]],
        )
