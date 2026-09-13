from __future__ import annotations
import logging
import re
from app.domain.graph.fact_policy import get_relation_policy
from app.domain.llm.contracts import GENERIC_ENTITY_REFERENCES, QUESTION_CLAUSE_RE
logger = logging.getLogger("services.llm_service")



class ExtractionPolicy:
    def __init__(self, config, **dependencies):
        self.config = config
        for name, value in dependencies.items():
            setattr(self, name, value)

    def contains_explicit_personal_assertion(self, user_message: str) -> bool:
        """Recognize a factual clause even when it is wrapped in a question."""
        normalized = " ".join(str(user_message or "").lower().split())
        subject = r"(?:aku|saya|gw|gue|nafiz|dia|ia|(?:pacar|ibu|ayah|teman|temen)ku)"
        target = r"(?!mana\b|siapa\b|apa\b|kapan\b)[\w][\w .'-]{1,80}"
        patterns = (
            rf"\b{subject}\b.{{0,35}}\b(?:kerja|bekerja|tinggal|kuliah|lahir|magang)\s+(?:di|pada|sebagai)\s+{target}",
            rf"\b{subject}\b.{{0,35}}\b(?:pindah|berasal|asal)\s+(?:ke|dari)\s+{target}",
            rf"\b{subject}\b.{{0,35}}\b(?:adalah|bernama|punya|memiliki|suka|benci|alergi)\s+{target}",
        )
        if any(re.search(pattern, normalized) for pattern in patterns):
            return True
        # Reminders with named subjects and explicit negation remain facts, even
        # when they start with "kamu ingat" instead of first-person language.
        return bool(re.search(rf"\b(?:tidak|gak|ga|nggak|enggak|bukan)\s+(?:lagi\s+)?tinggal\s+di\s+{target}", normalized)
                    and not QUESTION_CLAUSE_RE.search(normalized))

    def has_statement_in_question_turn(self, user_message: str) -> bool:
        """Conservatively detect a declarative clause wrapped in a question turn.

    The extraction fast-path may only skip a turn when it is clearly question-only.
    Clause boundaries are intentionally language-neutral; the extractor remains the
    authority on whether a candidate clause actually contains a fact.
    """
        text = " ".join(str(user_message or "").split())
        if not text:
            return False
        if not QUESTION_CLAUSE_RE.search(text) and "?" not in text:
            return False
        inner_statement = re.sub(
            r"^(?:apa(?:kah)?\s+kamu\s+(?:tahu|tau|ingat|inget)|"
            r"(?:do|can|could)\s+you\s+(?:know|remember))\s+(?:bahwa\s+|that\s+)?",
            "", text, flags=re.IGNORECASE,
        ).strip(" ?")
        if inner_statement != text.strip(" ?") and not QUESTION_CLAUSE_RE.search(inner_statement):
            if len(re.findall(r"[^\W_]+", inner_statement, flags=re.UNICODE)) >= 2:
                return True
        for clause in re.split(r"[.;,!?:]+", text):
            statement = clause.strip()
            if not statement or QUESTION_CLAUSE_RE.search(statement):
                continue
            words = re.findall(r"[^\W_]+", statement, flags=re.UNICODE)
            if len(words) < 2:
                continue
            # Topic-setting, commands, and conversational reactions are not facts.
            if re.match(
                r"^(?:kalau|jika|when|if|untuk|tentang|soal|mengenai|tolong|coba|"
                r"mahal|murah|wah|oh|oke|ok|iya|ya|hmm|hmmm)\b",
                statement,
                flags=re.IGNORECASE,
            ):
                continue
            return True
        return False

    def is_memory_recall_question(self, user_message: str) -> bool:
        """Detect information-seeking turns that contain no personal assertion."""
        normalized = " ".join(str(user_message or "").lower().split())
        if not normalized:
            return False
        if self.contains_explicit_personal_assertion(normalized):
            return False
    
        if self.has_statement_in_question_turn(user_message):
            return False
    
        if QUESTION_CLAUSE_RE.match(normalized):
            return True
        if re.search(
            r"^(?:aku|saya|gw|gue|nafiz|kamu)\s+(?:kerja|bekerja|tinggal|kuliah)\s+"
            r"(?:di\s+)?(?:mana|dimana)\b|"
            r"\b(?:harga|biaya|tarif)\b.*\bberapa\b|"
            r"^(?:mahal|murah)\b.*\b(?:mana|dimana|berapa)\b",
            normalized,
        ):
            return True
        if re.search(r"^(lah\s+kan|kamu\s+(?:masih\s+)?(?:ingat|inget|tau|tahu))\b", normalized):
            return True
        if re.search(r"\b(kamu|claire)\b.*\b(ingat|inget|tau|tahu)\b", normalized):
            return True
        return False

    def sanitize_extracted_knowledge(self, data: dict) -> dict:
        """Normalize harmless provider drift before strict schema validation."""
        if not isinstance(data, dict):
            return {"nodes": [], "edges": []}
    
        node_fields = {"id", "label", "name", "identity_context", "confidence"}
        edge_fields = {
            "source",
            "target",
            "relation",
            "supersedes",
            "replaces_current_relation",
            "confidence",
        }
        retraction_fields = {"source", "relation", "target", "fact_id", "confidence"}
        valid_nodes = []
        blocked_references = set()
        for node in data.get("nodes", []):
            if not isinstance(node, dict):
                continue
            name = " ".join(str(node.get("name", "")).strip().lower().split())
            if not name or name in GENERIC_ENTITY_REFERENCES:
                blocked_references.add(name)
                node_id = str(node.get("id", "")).strip()
                if node_id:
                    blocked_references.add(node_id)
                continue
            unknown_fields = set(node) - node_fields
            if unknown_fields:
                logger.warning(
                    "Ignoring unsupported knowledge-node fields: %s",
                    sorted(unknown_fields),
                )
            valid_nodes.append({field: node[field] for field in node_fields if field in node})
    
        valid_edges = []
        for edge in data.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = " ".join(str(edge.get("source", "")).strip().lower().split())
            target = " ".join(str(edge.get("target", "")).strip().lower().split())
            if not source or not target:
                continue
            if source in GENERIC_ENTITY_REFERENCES or target in GENERIC_ENTITY_REFERENCES:
                continue
            if source in blocked_references or target in blocked_references:
                continue
            unknown_fields = set(edge) - edge_fields
            if unknown_fields:
                logger.warning(
                    "Ignoring unsupported knowledge-edge fields: %s",
                    sorted(unknown_fields),
                )
            normalized_edge = {field: edge[field] for field in edge_fields if field in edge}
            try:
                policy = get_relation_policy(normalized_edge.get("relation", ""))
            except ValueError:
                policy = None
            if (
                policy is not None
                and policy.cardinality != "one"
                and normalized_edge.get("replaces_current_relation") is True
            ):
                # Provider output is probabilistic. A harmless flag mistake must
                # not poison/retry the entire durable memory job.
                normalized_edge["replaces_current_relation"] = False
            valid_edges.append(normalized_edge)
    
        valid_retractions = []
        for retraction in data.get("retractions", []):
            if not isinstance(retraction, dict):
                continue
            unknown_fields = set(retraction) - retraction_fields
            if unknown_fields:
                logger.warning("Ignoring unsupported retraction fields: %s", sorted(unknown_fields))
            valid_retractions.append(
                {field: retraction[field] for field in retraction_fields if field in retraction}
            )
    
        return {"nodes": valid_nodes, "edges": valid_edges, "retractions": valid_retractions}

    def validate_extraction_envelope(self, data: object) -> dict:
        """Reject malformed provider JSON before defaults can turn it into no-facts."""
        if not isinstance(data, dict):
            raise ValueError("knowledge extraction output must be a JSON object")
        for field in ("nodes", "edges"):
            if field not in data:
                raise ValueError(f"knowledge extraction output is missing required '{field}' array")
            if not isinstance(data[field], list):
                raise ValueError(f"knowledge extraction field '{field}' must be an array")
            if any(not isinstance(item, dict) for item in data[field]):
                raise ValueError(f"knowledge extraction field '{field}' must contain objects")
        if "retractions" in data and not isinstance(data["retractions"], list):
            raise ValueError("knowledge extraction field 'retractions' must be an array")
        if any(not isinstance(item, dict) for item in data.get("retractions", [])):
            raise ValueError("knowledge extraction field 'retractions' must contain objects")
        return data

    def format_extraction_history(self, session_history: list | None, limit: int = 12) -> str:
        """Render the immediately preceding dialogue as passive reference data."""
        if not session_history:
            return ""
    
        summary_messages = [
            message for message in session_history
            if isinstance(message, dict) and message.get("role") == "summary"
        ][-1:]
        dialogue_messages = [
            message for message in session_history
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
        ][-limit:]
    
        formatted = []
        for message in [*summary_messages, *dialogue_messages]:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in {"user", "assistant", "summary"}:
                continue
            content = str(message.get("content", "")).strip()
            if content:
                # Keep the extractor bounded even when an old message is unusually long.
                formatted.append({"role": role, "content": content[:1500]})
        return self.prompts.safe_context_json(formatted) if formatted else ""
