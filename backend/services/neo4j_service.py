from neo4j import GraphDatabase
from configs.settings import settings
import logging
import hashlib
import math
import re
import uuid
from datetime import datetime, timezone
from services.memory_policy import (
    RELATION_POLICIES,
    get_relation_policy,
    normalize_relation,
    validate_extracted_knowledge,
)

logger = logging.getLogger(__name__)

class Neo4jService:
    def __init__(self):
        self.available = False
        self.driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
        try:
            self.driver.verify_connectivity()
            self.available = True
            logger.info("Connected to Neo4j successfully!")
            
            # ``name`` is only a display value. It cannot be unique: two people
            # can legitimately share a name. Migrate old installations before
            # enforcing the contextual identity key used by new graph writes.
            with self.driver.session() as session:
                session.run("DROP CONSTRAINT unique_entity_name IF EXISTS")
                session.run("""
                    MATCH (e:Entity)
                    WHERE e.entity_key IS NULL
                    SET e.entity_key = 'legacy:' + elementId(e),
                        e.display_name = coalesce(e.display_name, e.name)
                """)
                session.run("CREATE CONSTRAINT unique_entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_key IS UNIQUE")
                session.run("CREATE CONSTRAINT unique_residence_retraction IF NOT EXISTS FOR (r:ResidenceRetraction) REQUIRE r.marker_key IS UNIQUE")
                session.run(
                    "CREATE CONSTRAINT unique_person_identity_registry IF NOT EXISTS "
                    "FOR (i:EntityIdentity) REQUIRE i.identity_key IS UNIQUE"
                )
                session.run("CREATE INDEX entity_name_lookup IF NOT EXISTS FOR (e:Entity) ON (e.name)")
                session.run(
                    "CREATE FULLTEXT INDEX entity_identity_search IF NOT EXISTS "
                    "FOR (e:Entity) ON EACH [e.name, e.identity_context]"
                )
                session.run("CALL db.awaitIndex('entity_identity_search', 30)")
                # Backfill temporal/provenance identifiers for relationships
                # created by older versions. randomUUID() is evaluated once
                # per relationship, so every fact remains individually editable.
                session.run("""
                    MATCH ()-[r]->()
                    SET r.fact_id = coalesce(r.fact_id, randomUUID()),
                        r.created_at = coalesce(r.created_at, r.updated_at, timestamp()),
                        r.last_confirmed_at = coalesce(r.last_confirmed_at, r.updated_at, r.created_at, timestamp()),
                        r.is_current = coalesce(r.is_current, true),
                        r.importance = coalesce(r.importance, 1.0),
                        r.memory_kind = coalesce(r.memory_kind, 'fact'),
                        r.review_status = coalesce(r.review_status, 'approved'),
                        r.scope = coalesce(r.scope, CASE WHEN r.project_id IS NULL THEN 'global' ELSE 'project' END),
                        r.scope_key = coalesce(r.scope_key, r.project_id, 'global'),
                        r.observed_at = coalesce(r.observed_at, r.created_at, timestamp()),
                        r.valid_from = coalesce(r.valid_from, r.created_at, timestamp())
                """)
                for relation, policy in RELATION_POLICIES.items():
                    session.run(
                        f"""
                        MATCH ()-[r:{relation}]->()
                        SET r.memory_kind = $memory_kind,
                            r.expires_at = CASE
                                WHEN $ttl_ms IS NULL THEN r.expires_at
                                ELSE coalesce(r.expires_at, coalesce(r.observed_at, r.created_at, timestamp()) + $ttl_ms)
                            END
                        """,
                        memory_kind=policy.kind,
                        ttl_ms=policy.ttl_milliseconds,
                    )
                session.run("""
                    MATCH ()-[r]->()
                    WHERE coalesce(r.is_current, true) = true
                      AND r.expires_at IS NOT NULL
                      AND r.expires_at <= timestamp()
                    SET r.is_current = false,
                        r.expired_at = timestamp(),
                        r.updated_at = timestamp()
                """)
                
        except Exception as e:
            self.available = False
            logger.error(f"Failed to connect to Neo4j: {e}")

    def close(self):
        self.driver.close()

    @staticmethod
    def _clean_label(label: str) -> str:
        clean_label = re.sub(r'[^a-zA-Z0-9_]', '', str(label or "Entity"))
        # Preserve PascalCase/acronyms exactly as supplied by the extractor.
        # Cypher labels must start with a letter when interpolated unquoted.
        if not clean_label or not clean_label[0].isalpha():
            return "Entity"
        return clean_label

    @staticmethod
    def _clean_name(name: str) -> str:
        return " ".join(str(name or "").strip().lower().split())

    @classmethod
    def _canonical_identity_context(cls, identity_context: str) -> str:
        """Normalize common relational paraphrases without erasing distinctions."""
        text = cls._clean_name(identity_context)
        text = re.sub(r"\b(?:temanku|temenku|my friend)\b", "teman nafiz", text)
        text = re.sub(r"\btemen\b", "teman", text)
        # Joined Indonesian possessives are descriptive evidence, not a stable
        # difference in identity ("ibunya nafiz" and "ibu dari nafiz").
        text = re.sub(r"\b(ibu|ayah|istri|suami|teman|kakak|adik)nya\b", r"\1", text)
        aliases = {
            "mother": "ibu", "mom": "ibu", "mama": "ibu", "mommy": "ibu",
            "father": "ayah", "dad": "ayah", "papa": "ayah",
            "wife": "istri", "spouse": "pasangan", "husband": "suami",
            "friend": "teman", "colleague": "rekan", "coworker": "rekan",
            "sister": "saudara perempuan", "brother": "saudara laki laki",
        }
        ignored = {"dari", "of", "the", "seorang", "a", "an", "milik", "punya"}
        tokens = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        canonical = [aliases.get(token, token) for token in tokens if token not in ignored]
        return " ".join(canonical)

    @staticmethod
    def _prepare_search_keyword(keyword: str) -> tuple[str, str] | None:
        """Build a Unicode word-boundary regex for one meaningful keyword."""
        tokens = re.findall(r"[^\W_]+", str(keyword or "").lower(), flags=re.UNICODE)
        normalized = " ".join(tokens)
        # Prevent noisy one/two-character router output ("a", "di", "an")
        # from fanning out across the graph. Meaningful abbreviations should be
        # emitted with context by the router (for example "ai engineer").
        if sum(len(token) for token in tokens) < 3:
            return None
        term_pattern = r"\s+".join(re.escape(token) for token in tokens)
        boundary_pattern = (
            rf"(?i).*(?<![\p{{L}}\p{{N}}]){term_pattern}"
            rf"(?![\p{{L}}\p{{N}}]).*"
        )
        return normalized, boundary_pattern

    @classmethod
    def _entity_key(cls, label: str, name: str, identity_context: str = "") -> str:
        """Return a safe graph identity key without treating a display name as ID.

        A named Person is only stable when the extractor supplies an explicit
        differentiator (for example, ``mother of nafiz``). Unqualified people
        are rejected instead of being permanently fragmented by random keys.
        """
        label = cls._clean_label(label).lower()
        name = cls._clean_name(name)
        context = cls._canonical_identity_context(identity_context)

        if label == "person" and name in {"nafiz", "claire"}:
            return f"person:{name}"
        if label == "person" and not context:
            raise ValueError("Non-canonical Person requires identity_context")

        canonical = f"{label}|{name}|{context}" if label == "person" else f"{label}|{name}"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{label}:{digest}"

    @staticmethod
    def _residence_marker_key(source, scope, target=None):
        return hashlib.sha256(
            repr((str(source), str(scope), str(target) if target is not None else None)).encode("utf-8")
        ).hexdigest()

    def merge_knowledge(
        self,
        nodes: list[dict],
        edges: list[dict],
        retractions: list[dict] | None = None,
        source_conversation_id: str | None = None,
        source_message_id: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        event_id: str | None = None,
        event_at: datetime | None = None,
    ) -> dict:
        """Apply one extracted memory event atomically and in event-time order."""
        validated = validate_extracted_knowledge(
            {"nodes": nodes, "edges": edges, "retractions": retractions or []}
        )
        nodes = validated["nodes"]
        edges = validated["edges"]
        retractions = validated.get("retractions", [])
        stable_event_id = str(event_id or source_message_id or uuid.uuid4())
        stable_event_at = event_at or datetime.now(timezone.utc)
        if stable_event_at.tzinfo is None:
            stable_event_at = stable_event_at.replace(tzinfo=timezone.utc)
        event_at_ms = int(stable_event_at.timestamp() * 1000)
        scope_key = str(project_id or "").strip() or "global"

        def apply(tx):
            invalidated: set[str] = set()
            project_entity_key = None
            if project_id:
                project_entity_key = f"project:{project_id}"
                tx.run(
                    """
                    MERGE (p:Entity:Project {entity_key: $entity_key})
                    ON CREATE SET p.created_at = timestamp(), p.importance = 1.0
                    SET p.name = $name, p.display_name = $display_name,
                        p.project_id = $project_id, p.updated_at = timestamp()
                    """,
                    entity_key=project_entity_key,
                    name=self._clean_name(project_name or project_id),
                    display_name=str(project_name or project_id).strip(),
                    project_id=project_id,
                )

            entities_by_ref: dict[str, dict] = {}
            refs_by_legacy_name: dict[str, list[str]] = {}
            for index, node in enumerate(nodes):
                label = self._clean_label(node.get("label", "Entity"))
                name = self._clean_name(node.get("name", ""))
                if not name:
                    continue
                identity_context = self._clean_name(node.get("identity_context", ""))
                identity_signature = self._canonical_identity_context(identity_context)
                is_active_project = bool(
                    project_entity_key
                    and label.lower() == "project"
                    and (
                        identity_context == self._clean_name(project_id)
                        or name in {
                            self._clean_name(project_id),
                            self._clean_name(project_name or project_id),
                        }
                    )
                )
                entity_key = (
                    project_entity_key
                    if is_active_project
                    else self._entity_key(label, name, identity_context)
                )
                identity_key = None
                if label.lower() == "person" and name not in {"nafiz", "claire"}:
                    identity_key = entity_key
                    # The registry lock serializes linking decisions for this
                    # identity. Its relationship survives display-name/key edits.
                    linked = tx.run(
                        """
                        MERGE (i:EntityIdentity {identity_key: $identity_key})
                        ON CREATE SET i.name = $name, i.canonical_context = $identity_signature,
                                      i.created_at = timestamp()
                        SET i.write_fence = $event_id, i.updated_at = timestamp()
                        WITH i
                        OPTIONAL MATCH (i)-[:RESOLVES_TO]->(person:Entity:Person)
                        RETURN collect(person.entity_key) AS linked_keys
                        """,
                        identity_key=identity_key, name=name,
                        identity_signature=identity_signature, event_id=stable_event_id,
                    ).single()
                    linked_keys = [key for key in (linked or {}).get("linked_keys", []) if key]
                    if not linked_keys:
                        candidates = tx.run(
                            """
                            MATCH (person:Entity:Person {name: $name})
                            RETURN person.entity_key AS entity_key,
                                   person.identity_context AS identity_context,
                                   person.identity_signature AS identity_signature
                            ORDER BY person.entity_key
                            LIMIT 51
                            """,
                            name=name,
                        )
                        matching_keys = []
                        candidate_count = 0
                        for candidate in candidates:
                            candidate_count += 1
                            signature = candidate.get("identity_signature") or self._canonical_identity_context(
                                candidate.get("identity_context", "")
                            )
                            if signature == identity_signature and candidate.get("entity_key"):
                                matching_keys.append(candidate["entity_key"])
                        linked_keys = sorted(set(matching_keys))
                        # A truncated candidate set cannot prove uniqueness.
                        if candidate_count >= 51:
                            linked_keys.append("candidate_budget_exceeded")
                    if len(linked_keys) > 1 or "candidate_budget_exceeded" in linked_keys:
                        tx.run(
                            """
                            MATCH (i:EntityIdentity {identity_key: $identity_key})
                            SET i.review_status = 'pending_ambiguous',
                                i.candidate_entity_keys = $candidate_keys
                            """,
                            identity_key=identity_key, candidate_keys=linked_keys,
                        )
                        if source_message_id:
                            invalidated.add(str(source_message_id))
                        logger.warning("Quarantining ambiguous Person identity %s", identity_key)
                        continue
                    if linked_keys:
                        entity_key = linked_keys[0]
                node_ref = str(node.get("id") or f"__legacy_node_{index}").strip()
                if not node_ref or node_ref in entities_by_ref:
                    continue
                tx.run(
                    f"""
                    MERGE (n:Entity {{entity_key: $entity_key}})
                    ON CREATE SET n.created_at = timestamp(), n.importance = 1.0,
                                  n.source_conversation_id = $source_conversation_id,
                                  n.source_message_id = $source_message_id
                    SET n:{label}, n.name = $name, n.display_name = $name,
                        n.identity_context = $identity_context,
                        n.identity_signature = $identity_signature,
                        n.identity_aliases = CASE
                            WHEN $identity_context IS NULL OR $identity_context IN coalesce(n.identity_aliases, [])
                            THEN coalesce(n.identity_aliases, [])
                            ELSE coalesce(n.identity_aliases, []) + [$identity_context] END,
                        n.updated_at = timestamp(),
                        n.importance = CASE WHEN
                            ($source_message_id IS NOT NULL AND $source_message_id IN coalesce(n.source_message_ids, []))
                            OR ($source_message_id IS NULL AND n.last_applied_event_id = $event_id)
                            OR $event_at < coalesce(n.latest_event_at, 0)
                            THEN coalesce(n.importance, 1.0) ELSE coalesce(n.importance, 1.0) + 0.5 END,
                        n.last_applied_event_id = $event_id,
                        n.latest_event_at = CASE WHEN $event_at >= coalesce(n.latest_event_at, 0)
                            THEN $event_at ELSE n.latest_event_at END,
                        n.source_conversation_id = coalesce(n.source_conversation_id, $source_conversation_id),
                        n.source_message_id = coalesce(n.source_message_id, $source_message_id),
                        n.last_source_conversation_id = coalesce($source_conversation_id, n.last_source_conversation_id),
                        n.last_source_message_id = coalesce($source_message_id, n.last_source_message_id),
                        n.source_conversation_ids = CASE
                            WHEN $source_conversation_id IS NULL OR $source_conversation_id IN coalesce(n.source_conversation_ids, [])
                            THEN coalesce(n.source_conversation_ids, [])
                            ELSE coalesce(n.source_conversation_ids, []) + [$source_conversation_id] END,
                        n.source_message_ids = CASE
                            WHEN $source_message_id IS NULL OR $source_message_id IN coalesce(n.source_message_ids, [])
                            THEN coalesce(n.source_message_ids, [])
                            ELSE coalesce(n.source_message_ids, []) + [$source_message_id] END
                    """,
                    entity_key=entity_key,
                    name=name,
                    identity_context=identity_context or None,
                    identity_signature=identity_signature or None,
                    source_conversation_id=source_conversation_id,
                    source_message_id=source_message_id,
                    event_id=stable_event_id,
                    event_at=event_at_ms,
                )
                if identity_key:
                    tx.run(
                        """
                        MATCH (i:EntityIdentity {identity_key: $identity_key})
                        MATCH (person:Entity {entity_key: $entity_key})
                        MERGE (i)-[:RESOLVES_TO]->(person)
                        SET i.review_status = 'approved', i.candidate_entity_keys = [],
                            i.identity_aliases = CASE
                                WHEN $identity_context IN coalesce(i.identity_aliases, [])
                                THEN coalesce(i.identity_aliases, [])
                                ELSE coalesce(i.identity_aliases, []) + [$identity_context] END
                        """,
                        identity_key=identity_key, entity_key=entity_key,
                        identity_context=identity_context,
                    )
                entities_by_ref[node_ref] = {
                    "entity_key": entity_key,
                    "name": name,
                    "confidence": float(node.get("confidence", 1.0)),
                }
                refs_by_legacy_name.setdefault(name, []).append(node_ref)
                if project_entity_key and label != "Project":
                    tx.run(
                        """
                        MATCH (n:Entity {entity_key: $entity_key})
                        MATCH (p:Entity:Project {entity_key: $project_entity_key})
                        MERGE (n)-[r:BELONGS_TO {scope_key: $scope_key}]->(p)
                        ON CREATE SET r.fact_id = randomUUID(), r.created_at = timestamp()
                        SET r.is_current = true, r.review_status = 'approved',
                            r.memory_kind = 'scope', r.project_id = $project_id,
                            r.scope = 'project', r.updated_at = timestamp(),
                            r.source_conversation_ids = CASE
                                WHEN $source_conversation_id IS NULL OR $source_conversation_id IN coalesce(r.source_conversation_ids, [])
                                THEN coalesce(r.source_conversation_ids, [])
                                ELSE coalesce(r.source_conversation_ids, []) + [$source_conversation_id] END,
                            r.source_message_ids = CASE
                                WHEN $source_message_id IS NULL OR $source_message_id IN coalesce(r.source_message_ids, [])
                                THEN coalesce(r.source_message_ids, [])
                                ELSE coalesce(r.source_message_ids, []) + [$source_message_id] END
                        """,
                        entity_key=entity_key,
                        project_entity_key=project_entity_key,
                        scope_key=scope_key,
                        project_id=project_id,
                        source_conversation_id=source_conversation_id,
                        source_message_id=source_message_id,
                    )

            def resolve_ref(raw: object) -> str | None:
                value = str(raw or "").strip()
                if value in entities_by_ref:
                    return value
                candidates = refs_by_legacy_name.get(self._clean_name(value), [])
                return candidates[0] if len(candidates) == 1 else None

            for edge in edges:
                source_ref = resolve_ref(edge.get("source"))
                target_ref = resolve_ref(edge.get("target"))
                relation_name = normalize_relation(edge.get("relation", "RELATED_TO"))
                if source_ref is None or target_ref is None:
                    logger.warning("Skipping unknown graph endpoints for %s", relation_name)
                    continue
                source = entities_by_ref[source_ref]["entity_key"]
                target = entities_by_ref[target_ref]["entity_key"]
                relation_policy = get_relation_policy(relation_name)
                proposed_fact_id = str(uuid.uuid4())
                supersedes = [str(item).strip() for item in edge.get("supersedes", []) if str(item).strip()]
                replaces_current_relation = edge.get("replaces_current_relation") is True
                confidence = min(
                    float(edge.get("confidence", 1.0)),
                    entities_by_ref[source_ref]["confidence"],
                    entities_by_ref[target_ref]["confidence"],
                )

                tx.run(
                    """
                    MATCH (a:Entity {entity_key: $source})
                    SET a.memory_write_fence = $event_id
                    """,
                    source=source,
                    event_id=stable_event_id,
                )
                conflicting_fact_ids: list[str] = []
                newest_conflict_event = 0
                residence_retracted_at = 0
                if relation_name == "LIVES_IN":
                    marker = tx.run(
                        """MATCH (m:ResidenceRetraction)
                        WHERE m.marker_key IN $marker_keys
                        RETURN coalesce(max(m.event_at), 0) AS retracted_event_at""",
                        marker_keys=[self._residence_marker_key(source, scope_key, target),
                                     self._residence_marker_key(source, scope_key)],
                    ).single()
                    residence_retracted_at = int((marker or {}).get("retracted_event_at") or 0)
                if relation_policy.cardinality == "one":
                    record = tx.run(
                        f"""
                        MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->(other:Entity)
                        WHERE other.entity_key <> $target
                          AND coalesce(old.scope_key, 'global') = $scope_key
                          AND coalesce(old.is_current, true) = true
                          AND coalesce(old.review_status, 'approved') = 'approved'
                          AND (old.expires_at IS NULL OR old.expires_at > timestamp())
                        RETURN collect(old.fact_id) AS fact_ids,
                               coalesce(max(CASE
                                   WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                                   THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END), 0) AS newest_event_at
                        """,
                        source=source,
                        target=target,
                        scope_key=scope_key,
                    ).single()
                    if record:
                        conflicting_fact_ids = [str(v) for v in (record.get("fact_ids") or []) if v]
                        newest_conflict_event = int(record.get("newest_event_at") or 0)
                explicit_resolution = replaces_current_relation or bool(set(conflicting_fact_ids) & set(supersedes))
                if confidence < settings.MEMORY_FACT_CONFIDENCE_THRESHOLD:
                    review_status = "pending_low_confidence"
                elif newest_conflict_event > event_at_ms or (residence_retracted_at and residence_retracted_at >= event_at_ms):
                    review_status = "pending_stale_event"
                elif conflicting_fact_ids and not explicit_resolution:
                    review_status = "pending_conflict"
                else:
                    review_status = "approved"
                approve_new_fact = review_status == "approved"
                if not approve_new_fact and source_message_id:
                    invalidated.add(str(source_message_id))

                record = tx.run(
                    f"""
                    MATCH (a:Entity {{entity_key: $source}})
                    MATCH (b:Entity {{entity_key: $target}})
                    MERGE (a)-[r:{relation_name} {{scope_key: $scope_key}}]->(b)
                    ON CREATE SET r.fact_id = $fact_id, r.created_at = timestamp(),
                                  r.source_event_at = $event_at,
                                  r.source_conversation_id = $source_conversation_id,
                                  r.source_message_id = $source_message_id
                    WITH a, b, r, NOT (
                        ($source_message_id IS NOT NULL AND $source_message_id IN coalesce(r.source_message_ids, []))
                        OR ($source_message_id IS NULL AND r.last_applied_event_id = $event_id)
                    ) AS new_event,
                         $event_at >= CASE
                             WHEN coalesce(r.lifecycle_event_at, 0) > coalesce(r.source_event_at, 0)
                             THEN r.lifecycle_event_at ELSE coalesce(r.source_event_at, 0) END AS newest_event
                    SET r.fact_id = coalesce(r.fact_id, $fact_id),
                        r.is_current = CASE WHEN newest_event THEN $approve_new_fact ELSE coalesce(r.is_current, true) END,
                        r.review_status = CASE WHEN newest_event THEN $review_status ELSE coalesce(r.review_status, 'approved') END,
                        r.confidence = CASE WHEN newest_event THEN $confidence ELSE coalesce(r.confidence, $confidence) END,
                        r.memory_kind = coalesce(r.memory_kind, $memory_kind),
                        r.observed_at = coalesce(r.observed_at, $event_at),
                        r.valid_from = coalesce(r.valid_from, $event_at),
                        r.expires_at = CASE WHEN newest_event AND $approve_new_fact AND $ttl_ms IS NOT NULL
                            THEN $event_at + $ttl_ms ELSE r.expires_at END,
                        r.last_confirmed_at = CASE WHEN newest_event AND $approve_new_fact
                            THEN $event_at ELSE coalesce(r.last_confirmed_at, r.created_at) END,
                        r.updated_at = timestamp(), r.scope = $scope, r.project_id = $project_id,
                        r.source_event_at = CASE WHEN newest_event THEN $event_at ELSE r.source_event_at END,
                        r.importance = CASE WHEN new_event AND newest_event AND $approve_new_fact
                            THEN coalesce(r.importance, 1.0) + 0.5 ELSE coalesce(r.importance, 1.0) END,
                        r.last_applied_event_id = $event_id,
                        r.superseded_at = CASE WHEN newest_event AND $approve_new_fact THEN null ELSE r.superseded_at END,
                        r.superseded_by = CASE WHEN newest_event AND $approve_new_fact THEN null ELSE r.superseded_by END,
                        r.source_conversation_id = coalesce(r.source_conversation_id, $source_conversation_id),
                        r.source_message_id = coalesce(r.source_message_id, $source_message_id),
                        r.last_source_conversation_id = coalesce($source_conversation_id, r.last_source_conversation_id),
                        r.last_source_message_id = coalesce($source_message_id, r.last_source_message_id),
                        r.source_conversation_ids = CASE
                            WHEN $source_conversation_id IS NULL OR $source_conversation_id IN coalesce(r.source_conversation_ids, [])
                            THEN coalesce(r.source_conversation_ids, []) ELSE coalesce(r.source_conversation_ids, []) + [$source_conversation_id] END,
                        r.source_message_ids = CASE
                            WHEN $source_message_id IS NULL OR $source_message_id IN coalesce(r.source_message_ids, [])
                            THEN coalesce(r.source_message_ids, []) ELSE coalesce(r.source_message_ids, []) + [$source_message_id] END,
                        a.importance = CASE WHEN new_event AND newest_event AND $approve_new_fact
                            THEN coalesce(a.importance, 1.0) + 0.1 ELSE coalesce(a.importance, 1.0) END,
                        b.importance = CASE WHEN new_event AND newest_event AND $approve_new_fact
                            THEN coalesce(b.importance, 1.0) + 0.1 ELSE coalesce(b.importance, 1.0) END
                    RETURN r.fact_id AS fact_id
                    """,
                    source=source, target=target, fact_id=proposed_fact_id,
                    source_conversation_id=source_conversation_id,
                    source_message_id=source_message_id, approve_new_fact=approve_new_fact,
                    review_status=review_status, confidence=confidence,
                    memory_kind=relation_policy.kind, ttl_ms=relation_policy.ttl_milliseconds,
                    scope_key=scope_key, scope="project" if project_id else "global",
                    project_id=project_id, event_id=stable_event_id, event_at=event_at_ms,
                ).single()
                actual_fact_id = record["fact_id"] if record else proposed_fact_id
                old_ids = [item for item in supersedes if item != actual_fact_id]
                if approve_new_fact and old_ids:
                    rows = tx.run(
                        f"""
                        MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->()
                        WHERE old.fact_id IN $old_fact_ids
                          AND coalesce(old.scope_key, 'global') = $scope_key
                          AND coalesce(old.is_current, true) = true
                          AND CASE WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                              THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END <= $event_at
                        SET old.is_current = false, old.superseded_at = $event_at,
                            old.superseded_by = $new_fact_id, old.lifecycle_event_at = $event_at,
                            old.updated_at = timestamp()
                        RETURN coalesce(old.source_message_ids, []) +
                               CASE WHEN old.source_message_id IS NULL THEN [] ELSE [old.source_message_id] END AS source_message_ids
                        """,
                        source=source, old_fact_ids=old_ids, new_fact_id=actual_fact_id,
                        scope_key=scope_key, event_at=event_at_ms,
                    )
                    for row in rows:
                        invalidated.update(str(v) for v in (row.get("source_message_ids") or []) if v)
                if approve_new_fact and replaces_current_relation:
                    rows = tx.run(
                        f"""
                        MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->()
                        WHERE old.fact_id <> $new_fact_id
                          AND coalesce(old.scope_key, 'global') = $scope_key
                          AND coalesce(old.is_current, true) = true
                          AND CASE WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                              THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END <= $event_at
                        SET old.is_current = false, old.superseded_at = $event_at,
                            old.superseded_by = $new_fact_id, old.lifecycle_event_at = $event_at,
                            old.updated_at = timestamp()
                        RETURN coalesce(old.source_message_ids, []) +
                               CASE WHEN old.source_message_id IS NULL THEN [] ELSE [old.source_message_id] END AS source_message_ids
                        """,
                        source=source, new_fact_id=actual_fact_id,
                        scope_key=scope_key, event_at=event_at_ms,
                    )
                    for row in rows:
                        invalidated.update(str(v) for v in (row.get("source_message_ids") or []) if v)

            for retraction in retractions:
                relation_name = normalize_relation(retraction.get("relation", "RELATED_TO"))
                source_ref = resolve_ref(retraction.get("source"))
                target_ref = resolve_ref(retraction.get("target")) if retraction.get("target") else None
                if source_ref is None:
                    continue
                if retraction.get("target") and target_ref is None:
                    continue
                retraction_confidence = min(
                    float(retraction.get("confidence", 1.0)),
                    entities_by_ref[source_ref]["confidence"],
                    entities_by_ref[target_ref]["confidence"] if target_ref else 1.0,
                )
                if retraction_confidence < settings.MEMORY_FACT_CONFIDENCE_THRESHOLD:
                    if source_message_id:
                        invalidated.add(str(source_message_id))
                    continue
                source = entities_by_ref[source_ref]["entity_key"]
                target_key = entities_by_ref[target_ref]["entity_key"] if target_ref else None
                # Retire-before-write must survive an older job arriving later.
                # Fact-ID-specific retractions retain their existing narrow scope.
                if relation_name == "LIVES_IN" and not retraction.get("fact_id"):
                    tx.run("MATCH (a:Entity {entity_key: $source}) SET a.memory_write_fence = $event_id",
                           source=source, event_id=stable_event_id)
                    tx.run(
                        """MERGE (m:ResidenceRetraction {marker_key: $marker_key})
                        ON CREATE SET m.created_at = timestamp()
                        SET m.source_key = $source, m.target_key = $target, m.scope_key = $scope_key,
                            m.event_id = CASE WHEN $event_at >= coalesce(m.event_at, 0) THEN $event_id ELSE m.event_id END,
                            m.event_at = CASE WHEN $event_at >= coalesce(m.event_at, 0) THEN $event_at ELSE m.event_at END,
                            m.updated_at = timestamp()""",
                        marker_key=self._residence_marker_key(source, scope_key, target_key),
                        source=source, target=target_key, scope_key=scope_key,
                        event_at=event_at_ms, event_id=stable_event_id,
                    )
                rows = tx.run(
                    f"""
                    MATCH (a:Entity {{entity_key: $source}})-[old:{relation_name}]->(b:Entity)
                    WHERE coalesce(old.scope_key, 'global') = $scope_key
                      AND coalesce(old.is_current, true) = true
                      AND CASE WHEN coalesce(old.lifecycle_event_at, 0) > coalesce(old.source_event_at, 0)
                          THEN old.lifecycle_event_at ELSE coalesce(old.source_event_at, 0) END <= $event_at
                      AND ($fact_id IS NULL OR old.fact_id = $fact_id)
                      AND ($target IS NULL OR b.entity_key = $target)
                    SET old.is_current = false, old.retracted_at = $event_at,
                        old.retracted_by_event_id = $event_id,
                        old.lifecycle_event_at = $event_at, old.updated_at = timestamp()
                    RETURN coalesce(old.source_message_ids, []) +
                           CASE WHEN old.source_message_id IS NULL THEN [] ELSE [old.source_message_id] END AS source_message_ids
                    """,
                    source=source, target=target_key,
                    fact_id=retraction.get("fact_id"), scope_key=scope_key,
                    event_at=event_at_ms, event_id=stable_event_id,
                )
                retracted_any = False
                for row in rows:
                    retracted_any = True
                    invalidated.update(str(v) for v in (row.get("source_message_ids") or []) if v)
                if not retracted_any and source_message_id:
                    invalidated.add(str(source_message_id))

            return {"invalidated_source_message_ids": sorted(invalidated)}

        with self.driver.session() as session:
            if hasattr(session, "execute_write"):
                return session.execute_write(apply)
            return apply(session)

    def search_knowledge(
        self,
        keywords: list[str],
        *,
        include_historical: bool = False,
        project_id: str | None = None,
    ) -> list[str]:
        """
        Mencari fakta di Neo4j berdasarkan keywords/entities yang di-mention user.
        Mengembalikan list kalimat relasi agar mudah dibaca oleh LLM.
        """
        facts = []
        if not keywords:
            return facts

        prepared_keywords = []
        for keyword in keywords:
            prepared = self._prepare_search_keyword(keyword)
            if prepared:
                normalized, pattern = prepared
                if normalized not in {item["normalized"] for item in prepared_keywords}:
                    prepared_keywords.append({"normalized": normalized, "pattern": pattern})
            else:
                logger.info("Skipping noisy graph-search keyword: %r", keyword)
        if not prepared_keywords:
            return facts
            
        exact_keywords = [item["normalized"] for item in prepared_keywords]
        fulltext_query = " OR ".join(
            f'"{item["normalized"]}"'
            for item in prepared_keywords
        )
        first_keyword = prepared_keywords[0]

        with self.driver.session() as session:
            query = """
                CALL () {
                  CALL db.index.fulltext.queryNodes(
                    'entity_identity_search', $fulltext_query, {limit: 64}
                  ) YIELD node, score
                  RETURN node, score
                  UNION
                  MATCH (node:Entity)
                  WHERE node.name IN $exact_keywords
                  RETURN node, 10.0 AS score
                }
                WITH node, max(score) AS candidate_score
                ORDER BY candidate_score DESC
                LIMIT 64
                MATCH (node)-[candidate_relation]-(other:Entity)
                WITH startNode(candidate_relation) AS n,
                              candidate_relation AS r,
                              endNode(candidate_relation) AS m,
                              max(candidate_score) AS candidate_score
                WHERE coalesce(r.review_status, 'approved') = 'approved'
                  AND type(r) <> 'BELONGS_TO'
                  AND (
                    ($project_id IS NOT NULL AND r.project_id = $project_id)
                    OR coalesce(r.scope, CASE WHEN r.project_id IS NULL THEN 'global' ELSE 'project' END) = 'global'
                  )
                  AND ($include_historical OR (
                        coalesce(r.is_current, true) = true
                        AND (r.expires_at IS NULL OR r.expires_at > timestamp())
                  ))
                  AND (
                       coalesce(n.name, '') =~ $token_pattern
                       OR coalesce(m.name, '') =~ $token_pattern
                       OR replace(toLower(type(r)), '_', ' ') =~ $token_pattern
                       OR any(item IN $remaining_keywords WHERE
                            coalesce(n.name, '') =~ item.pattern
                            OR coalesce(m.name, '') =~ item.pattern
                            OR replace(toLower(type(r)), '_', ' ') =~ item.pattern)
                  )
                WITH n, r, m,
                     CASE WHEN $project_id IS NOT NULL AND r.project_id = $project_id THEN 2 ELSE 1 END AS scope_score,
                     size([item IN $prepared_keywords WHERE
                         coalesce(n.name, '') =~ item.pattern
                         OR coalesce(m.name, '') =~ item.pattern
                         OR replace(toLower(type(r)), '_', ' ') =~ item.pattern]) AS coverage_score,
                     size([item IN $prepared_keywords WHERE
                         coalesce(n.name, '') =~ item.pattern
                         OR coalesce(m.name, '') =~ item.pattern]) AS entity_score,
                     size([item IN $prepared_keywords WHERE
                         replace(toLower(type(r)), '_', ' ') =~ item.pattern]) AS relation_score,
                     candidate_score,
                     (coalesce(n.importance, 1.0) + coalesce(m.importance, 1.0) + coalesce(r.importance, 1.0)) AS importance_score,
                     coalesce(r.last_confirmed_at, r.updated_at, r.created_at, 0) AS recency_score
                ORDER BY CASE WHEN entity_score > 0 AND relation_score > 0 THEN 1 ELSE 0 END DESC,
                         coverage_score DESC, scope_score DESC, candidate_score DESC,
                         importance_score DESC, recency_score DESC
                LIMIT 20
                RETURN n.name, type(r), m.name, labels(n) AS n_labels, labels(m) AS m_labels,
                       n.identity_context AS n_identity_context, m.identity_context AS m_identity_context,
                       r.fact_id AS fact_id, coalesce(r.is_current, true) AS is_current,
                       recency_score AS last_confirmed_at,
                       coalesce(r.memory_kind, 'fact') AS memory_kind,
                       coalesce(r.scope, CASE WHEN r.project_id IS NULL THEN 'global' ELSE 'project' END) AS scope,
                       r.project_id AS project_id,
                       r.observed_at AS observed_at, r.expires_at AS expires_at
                """
            result = session.run(
                query,
                kw=first_keyword["normalized"],
                token_pattern=first_keyword["pattern"],
                remaining_keywords=prepared_keywords[1:],
                prepared_keywords=prepared_keywords,
                exact_keywords=exact_keywords,
                fulltext_query=fulltext_query,
                include_historical=include_historical,
                project_id=project_id,
            )
            for record in result:
                    n_labels = record['n_labels']
                    m_labels = record['m_labels']
                    n_label = next((l for l in n_labels if l != "Entity"), "Entity") if n_labels else "Entity"
                    m_label = next((l for l in m_labels if l != "Entity"), "Entity") if m_labels else "Entity"
                    
                    n_context = record.get("n_identity_context")
                    m_context = record.get("m_identity_context")
                    n_hint = f"; identity: {n_context}" if n_context else ""
                    m_hint = f"; identity: {m_context}" if m_context else ""
                    confirmed_at = record.get("last_confirmed_at")
                    if confirmed_at:
                        confirmed_iso = datetime.fromtimestamp(
                            confirmed_at / 1000,
                            tz=timezone.utc,
                        ).isoformat()
                    else:
                        confirmed_iso = "unknown"
                    fact_id = record.get("fact_id") or "legacy-unknown"
                    is_current = bool(record.get("is_current"))
                    memory_kind = record.get("memory_kind") or "fact"
                    fact_scope = record.get("scope") or "global"
                    fact_project_id = record.get("project_id")
                    expires_at = record.get("expires_at")
                    fact_str = (
                        f"[fact_id: {fact_id}; current: {str(is_current).lower()}; "
                        f"kind: {memory_kind}; scope: {fact_scope}; "
                        f"project_id: {fact_project_id or 'none'}; last_confirmed_at: {confirmed_iso}; "
                        f"expires_at_ms: {expires_at or 'none'}] "
                        f"({n_label} '{record['n.name']}'{n_hint}) "
                        f"--[{record['type(r)']}]--> "
                        f"({m_label} '{record['m.name']}'{m_hint})"
                    )
                    facts.append(fact_str)

        # Do not use set(facts): it discards the ranking order established by
        # Cypher. Preserve the first (highest-ranked) occurrence instead.
        unique_facts = []
        seen = set()
        for fact in facts:
            if fact not in seen:
                seen.add(fact)
                unique_facts.append(fact)
        return unique_facts

    def get_graph_data(self, limit=300, include_inactive: bool = False):
        """
        Mengambil nodes dan edges untuk visualisasi graph di frontend.
        """
        nodes_dict = {}
        links = []
        
        with self.driver.session() as session:
            query = """
            MATCH (n:Entity)-[r]->(m:Entity)
            WHERE $include_inactive OR (
                coalesce(r.is_current, true) = true
                AND coalesce(r.review_status, 'approved') = 'approved'
                AND (r.expires_at IS NULL OR r.expires_at > timestamp())
            )
            RETURN id(n) AS source_id, n.entity_key AS source_key, n.name AS source_name,
                   n.identity_context AS source_identity_context, labels(n) AS source_labels,
                   coalesce(n.importance, 1.0) AS source_importance,
                   n.source_conversation_id AS source_node_conversation_id,
                   n.source_message_id AS source_node_message_id,
                   n.source_conversation_ids AS source_node_conversation_ids,
                   n.source_message_ids AS source_node_message_ids,
                   type(r) AS rel_type, r.fact_id AS fact_id,
                   coalesce(r.is_current, true) AS is_current,
                   r.created_at AS fact_created_at,
                   r.last_confirmed_at AS last_confirmed_at,
                   r.superseded_at AS superseded_at,
                   r.superseded_by AS superseded_by,
                   coalesce(r.memory_kind, 'fact') AS memory_kind,
                   coalesce(r.review_status, 'approved') AS review_status,
                   coalesce(r.confidence, 1.0) AS confidence,
                   r.observed_at AS observed_at,
                   r.valid_from AS valid_from,
                   r.expires_at AS expires_at,
                   r.expired_at AS expired_at,
                   r.source_conversation_id AS fact_source_conversation_id,
                   r.source_message_id AS fact_source_message_id,
                   r.last_source_conversation_id AS fact_last_source_conversation_id,
                   r.last_source_message_id AS fact_last_source_message_id,
                   r.source_conversation_ids AS fact_source_conversation_ids,
                   r.source_message_ids AS fact_source_message_ids,
                   id(m) AS target_id, m.entity_key AS target_key, m.name AS target_name,
                   m.identity_context AS target_identity_context, labels(m) AS target_labels,
                   coalesce(m.importance, 1.0) AS target_importance,
                   m.source_conversation_id AS target_node_conversation_id,
                   m.source_message_id AS target_node_message_id,
                   m.source_conversation_ids AS target_node_conversation_ids,
                   m.source_message_ids AS target_node_message_ids
            ORDER BY coalesce(r.is_current, true) DESC,
                     coalesce(r.last_confirmed_at, r.updated_at, r.created_at, 0) DESC
            LIMIT $limit
            """
            result = session.run(query, limit=limit, include_inactive=include_inactive)
            
            for record in result:
                s_id = str(record["source_id"])
                s_labels = record["source_labels"]
                s_label = next((l for l in s_labels if l != "Entity"), "Entity") if s_labels else "Entity"
                
                if s_id not in nodes_dict:
                    nodes_dict[s_id] = {
                        "id": s_id,
                        "entity_key": record["source_key"],
                        "name": record["source_name"] or "Unknown",
                        "label": s_label,
                        "identity_context": record["source_identity_context"],
                        "importance": record["source_importance"],
                        "source_conversation_id": record["source_node_conversation_id"],
                        "source_message_id": record["source_node_message_id"],
                        "source_conversation_ids": record["source_node_conversation_ids"] or [],
                        "source_message_ids": record["source_node_message_ids"] or [],
                    }
                    
                t_id = str(record["target_id"])
                t_labels = record["target_labels"]
                t_label = next((l for l in t_labels if l != "Entity"), "Entity") if t_labels else "Entity"
                
                if t_id not in nodes_dict:
                    nodes_dict[t_id] = {
                        "id": t_id,
                        "entity_key": record["target_key"],
                        "name": record["target_name"] or "Unknown",
                        "label": t_label,
                        "identity_context": record["target_identity_context"],
                        "importance": record["target_importance"],
                        "source_conversation_id": record["target_node_conversation_id"],
                        "source_message_id": record["target_node_message_id"],
                        "source_conversation_ids": record["target_node_conversation_ids"] or [],
                        "source_message_ids": record["target_node_message_ids"] or [],
                    }
                    
                links.append({
                    "id": record["fact_id"],
                    "source": s_id,
                    "target": t_id,
                    "label": record["rel_type"],
                    "is_current": record["is_current"],
                    "created_at": record["fact_created_at"],
                    "last_confirmed_at": record["last_confirmed_at"],
                    "superseded_at": record["superseded_at"],
                    "superseded_by": record["superseded_by"],
                    "memory_kind": record["memory_kind"],
                    "review_status": record["review_status"],
                    "confidence": record["confidence"],
                    "observed_at": record["observed_at"],
                    "valid_from": record["valid_from"],
                    "expires_at": record["expires_at"],
                    "expired_at": record["expired_at"],
                    "source_conversation_id": record["fact_source_conversation_id"],
                    "source_message_id": record["fact_source_message_id"],
                    "last_source_conversation_id": record["fact_last_source_conversation_id"],
                    "last_source_message_id": record["fact_last_source_message_id"],
                    "source_conversation_ids": record["fact_source_conversation_ids"] or [],
                    "source_message_ids": record["fact_source_message_ids"] or [],
                })
                
        return {
            "nodes": list(nodes_dict.values()),
            "links": links
        }

    def delete_node(self, entity_key: str) -> dict | None:
        """Delete exactly one entity and its relationships by stable identity."""
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (n:Entity {entity_key: $entity_key})
                OPTIONAL MATCH (identity:EntityIdentity)-[:RESOLVES_TO]->(n)
                WITH n, collect(identity) AS identities, {
                    entity_key: n.entity_key,
                    name: n.name,
                    identity_context: n.identity_context
                } AS deleted
                FOREACH (identity IN identities | DETACH DELETE identity)
                DETACH DELETE n
                RETURN deleted
                """,
                entity_key=entity_key,
            ).single()
            return dict(record["deleted"]) if record else None

    def update_node(self, entity_key: str, updates: dict) -> dict | None:
        """Correct whitelisted entity properties without name-based targeting."""
        if not updates:
            raise ValueError("At least one node field must be supplied")

        allowed = {"name", "identity_context", "importance"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported node fields: {', '.join(sorted(unknown))}")
        if "importance" in updates and updates["importance"] is None:
            raise ValueError("Node importance cannot be null")

        with self.driver.session() as session:
            current = session.run(
                """
                MATCH (n:Entity {entity_key: $entity_key})
                RETURN n.name AS name, n.identity_context AS identity_context,
                       n.importance AS importance, labels(n) AS labels
                """,
                entity_key=entity_key,
            ).single()
            if not current:
                return None

            labels = current["labels"] or []
            label = next((item for item in labels if item != "Entity"), "Entity")
            new_name = self._clean_name(updates.get("name", current["name"]))
            if not new_name:
                raise ValueError("Node name cannot be empty")
            new_context = self._clean_name(
                updates.get("identity_context", current["identity_context"] or "")
            )
            identity_changed = "name" in updates or "identity_context" in updates
            new_entity_key = (
                self._entity_key(label, new_name, new_context)
                if identity_changed
                else entity_key
            )

            if new_entity_key != entity_key:
                conflict = session.run(
                    """
                    MATCH (n:Entity {entity_key: $new_entity_key})
                    RETURN count(n) AS count
                    """,
                    new_entity_key=new_entity_key,
                ).single()
                if conflict and conflict["count"]:
                    raise ValueError("The corrected identity already exists; refusing an implicit merge")

            importance = updates.get("importance", current["importance"] or 1.0)
            record = session.run(
                """
                MATCH (n:Entity {entity_key: $entity_key})
                SET n.entity_key = $new_entity_key,
                    n.name = $name,
                    n.display_name = $name,
                    n.identity_context = $identity_context,
                    n.identity_signature = $identity_signature,
                    n.importance = $importance,
                    n.updated_at = timestamp()
                RETURN n.entity_key AS entity_key, n.name AS name,
                       n.identity_context AS identity_context,
                       n.importance AS importance, labels(n) AS labels
                """,
                entity_key=entity_key,
                new_entity_key=new_entity_key,
                name=new_name,
                identity_context=new_context or None,
                identity_signature=self._canonical_identity_context(new_context) or None,
                importance=importance,
            ).single()
            return dict(record) if record else None

    def delete_fact(self, fact_id: str) -> dict | None:
        """Delete one relationship/fact while leaving both entities intact."""
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (source:Entity)-[r]->(target:Entity)
                WHERE r.fact_id = $fact_id
                WITH r, source.name AS source, target.name AS target,
                     type(r) AS relation, properties(r) AS properties,
                     coalesce(r.source_message_ids, []) +
                     CASE WHEN r.source_message_id IS NULL THEN [] ELSE [r.source_message_id] END AS source_message_ids
                DELETE r
                RETURN source, target, relation, properties, source_message_ids
                """,
                fact_id=fact_id,
            ).single()
            return dict(record) if record else None

    def update_fact(self, fact_id: str, updates: dict) -> dict | None:
        """Correct temporal/importance state for one relationship fact."""
        if not updates:
            raise ValueError("At least one fact field must be supplied")

        allowed = {"is_current", "importance"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported fact fields: {', '.join(sorted(unknown))}")
        if "is_current" in updates and updates["is_current"] is None:
            raise ValueError("Fact is_current cannot be null")
        if "importance" in updates and updates["importance"] is None:
            raise ValueError("Fact importance cannot be null")

        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (source:Entity)-[r]->(target:Entity)
                WHERE r.fact_id = $fact_id
                SET r.is_current = CASE
                        WHEN $set_is_current THEN $is_current
                        ELSE coalesce(r.is_current, true)
                    END,
                    r.importance = CASE
                        WHEN $set_importance THEN $importance
                        ELSE coalesce(r.importance, 1.0)
                    END,
                    r.last_confirmed_at = CASE
                        WHEN $set_is_current AND $is_current THEN timestamp()
                        ELSE r.last_confirmed_at
                    END,
                    r.superseded_at = CASE
                        WHEN $set_is_current AND NOT $is_current THEN timestamp()
                        WHEN $set_is_current AND $is_current THEN null
                        ELSE r.superseded_at
                    END,
                    r.superseded_by = CASE
                        WHEN $set_is_current AND $is_current THEN null
                        ELSE r.superseded_by
                    END,
                    r.review_status = CASE
                        WHEN $set_is_current AND $is_current THEN 'approved'
                        ELSE coalesce(r.review_status, 'approved')
                    END,
                    r.updated_at = timestamp()
                RETURN r.fact_id AS fact_id, source.name AS source,
                       target.name AS target, type(r) AS relation,
                       r.is_current AS is_current,
                       r.importance AS importance,
                       r.created_at AS created_at,
                       r.last_confirmed_at AS last_confirmed_at,
                       r.superseded_at AS superseded_at,
                       r.superseded_by AS superseded_by,
                       r.review_status AS review_status,
                       coalesce(r.source_message_ids, []) +
                       CASE WHEN r.source_message_id IS NULL THEN [] ELSE [r.source_message_id] END AS source_message_ids
                """,
                fact_id=fact_id,
                set_is_current="is_current" in updates,
                is_current=updates.get("is_current", True),
                set_importance="importance" in updates,
                importance=updates.get("importance", 1.0),
            ).single()
            return dict(record) if record else None

    def get_stats(self) -> dict:
        """Mengambil total nodes dan edges di Knowledge Graph"""
        try:
            with self.driver.session() as session:
                nodes_count = session.run("MATCH (n:Entity) RETURN count(n) AS count").single()["count"]
                edges_count = session.run("MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS count").single()["count"]
                return {"nodes": nodes_count, "edges": edges_count, "available": True}
        except Exception as e:
            logger.error(f"Error getting neo4j stats: {e}")
            return {"nodes": 0, "edges": 0, "available": False, "error": str(e)}

    def remove_conversation_provenance(
        self,
        conversation_id: str,
        message_ids: list[str] | None = None,
    ) -> dict:
        """Remove one deleted conversation's evidence from graph memory.

        Facts remain only when another conversation still supports them. Facts
        whose sole source was the deleted conversation are removed, and any
        newly orphaned entity is removed as well. This makes deleting a chat
        mean deleting the long-term memory derived exclusively from that chat.
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")

        source_message_ids = list({str(item) for item in (message_ids or []) if item})
        stats = {
            "relationships_unlinked": 0,
            "facts_deleted": 0,
            "nodes_unlinked": 0,
            "orphan_nodes_deleted": 0,
        }
        with self.driver.session() as session:
            relationship_cleanup = session.run(
                """
                MATCH ()-[r]->()
                WHERE r.source_conversation_id = $conversation_id
                   OR r.last_source_conversation_id = $conversation_id
                   OR $conversation_id IN coalesce(r.source_conversation_ids, [])
                WITH r,
                     [item IN coalesce(r.source_conversation_ids, [])
                      WHERE item <> $conversation_id] AS remaining_conversation_ids,
                     [item IN coalesce(r.source_message_ids, [])
                      WHERE NOT (item IN $source_message_ids)] AS remaining_message_ids
                SET r.source_conversation_ids = remaining_conversation_ids,
                    r.source_message_ids = remaining_message_ids,
                    r.source_conversation_id = CASE
                        WHEN r.source_conversation_id = $conversation_id THEN null
                        ELSE r.source_conversation_id
                    END,
                    r.source_message_id = CASE
                        WHEN r.source_message_id IN $source_message_ids THEN null
                        ELSE r.source_message_id
                    END,
                    r.last_source_conversation_id = CASE
                        WHEN r.last_source_conversation_id = $conversation_id THEN null
                        ELSE r.last_source_conversation_id
                    END,
                    r.last_source_message_id = CASE
                        WHEN r.last_source_message_id IN $source_message_ids THEN null
                        ELSE r.last_source_message_id
                    END,
                    r.source_deleted = true,
                    r.updated_at = timestamp()
                RETURN count(r) AS count
                """,
                conversation_id=conversation_id,
                source_message_ids=source_message_ids,
            ).single()
            stats["relationships_unlinked"] = relationship_cleanup["count"] if relationship_cleanup else 0

            delete_facts = session.run(
                """
                MATCH ()-[r]->()
                WHERE coalesce(r.source_deleted, false) = true
                  AND r.source_conversation_id IS NULL
                  AND size(coalesce(r.source_conversation_ids, [])) = 0
                DELETE r
                RETURN count(r) AS count
                """
            ).single()
            stats["facts_deleted"] = delete_facts["count"] if delete_facts else 0

            node_cleanup = session.run(
                """
                MATCH (n:Entity)
                WHERE n.source_conversation_id = $conversation_id
                   OR n.last_source_conversation_id = $conversation_id
                   OR $conversation_id IN coalesce(n.source_conversation_ids, [])
                WITH n,
                     [item IN coalesce(n.source_conversation_ids, [])
                      WHERE item <> $conversation_id] AS remaining_conversation_ids,
                     [item IN coalesce(n.source_message_ids, [])
                      WHERE NOT (item IN $source_message_ids)] AS remaining_message_ids
                SET n.source_conversation_ids = remaining_conversation_ids,
                    n.source_message_ids = remaining_message_ids,
                    n.source_conversation_id = CASE
                        WHEN n.source_conversation_id = $conversation_id THEN null
                        ELSE n.source_conversation_id
                    END,
                    n.source_message_id = CASE
                        WHEN n.source_message_id IN $source_message_ids THEN null
                        ELSE n.source_message_id
                    END,
                    n.last_source_conversation_id = CASE
                        WHEN n.last_source_conversation_id = $conversation_id THEN null
                        ELSE n.last_source_conversation_id
                    END,
                    n.last_source_message_id = CASE
                        WHEN n.last_source_message_id IN $source_message_ids THEN null
                        ELSE n.last_source_message_id
                    END,
                    n.source_deleted = true,
                    n.updated_at = timestamp()
                RETURN count(n) AS count
                """,
                conversation_id=conversation_id,
                source_message_ids=source_message_ids,
            ).single()
            stats["nodes_unlinked"] = node_cleanup["count"] if node_cleanup else 0

            delete_orphans = session.run(
                """
                MATCH (n:Entity)
                WHERE coalesce(n.source_deleted, false) = true
                  AND n.source_conversation_id IS NULL
                  AND size(coalesce(n.source_conversation_ids, [])) = 0
                  AND NOT EXISTS { MATCH (n)-[r]-() WHERE type(r) <> 'RESOLVES_TO' }
                DETACH DELETE n
                RETURN count(n) AS count
                """
            ).single()
            stats["orphan_nodes_deleted"] = delete_orphans["count"] if delete_orphans else 0
            session.run(
                "MATCH (identity:EntityIdentity) "
                "WHERE NOT (identity)-[:RESOLVES_TO]->() DETACH DELETE identity"
            )

        logger.info("Removed graph provenance for conversation %s: %s", conversation_id, stats)
        return stats

    def consolidate_memory(self, days_passed: float = 1.0) -> dict:
        """
        Background Job: Perawatan memori agar Neo4j tidak membengkak (Hairball Prevention).
        1. Decay: Mengurangi importance berdasarkan akumulasi hari lewat (0.9 ^ days_passed)
        2. Prune Orphans: Menghapus node yatim tanpa relasi.
        3. Forget: Menghapus node lama berimportance rendah *hanya* jika node
           tidak mendukung fact yang masih current.
        """
        requested_days = float(days_passed)
        if not math.isfinite(requested_days):
            raise ValueError("days_passed must be a finite number")
        safe_days_passed = min(max(requested_days, 0.0), 30.0)
        if safe_days_passed != requested_days:
            logger.warning("Clamped memory consolidation days from %s to %s", requested_days, safe_days_passed)
        stats = {
            "expired_states": 0,
            "decayed": 0,
            "pruned_orphans": 0,
            "forgotten_nodes": 0,
            "protected_current_nodes": 0,
        }
        decay_factor = 0.9 ** safe_days_passed
        
        try:
            with self.driver.session() as session:
                expiration_result = session.run("""
                    MATCH ()-[r]->()
                    WHERE coalesce(r.is_current, true) = true
                      AND r.expires_at IS NOT NULL
                      AND r.expires_at <= timestamp()
                    SET r.is_current = false,
                        r.expired_at = timestamp(),
                        r.updated_at = timestamp()
                    RETURN count(r) AS count
                """)
                stats["expired_states"] = expiration_result.single()["count"]

                # 1. Decay importance
                query = "MATCH (n:Entity) WHERE n.importance IS NOT NULL SET n.importance = n.importance * $decay RETURN count(n) AS count"
                result = session.run(query, decay=decay_factor)
                stats["decayed"] = result.single()["count"]
                
                protected_query = """
                MATCH (n:Entity)
                WHERE EXISTS {
                    MATCH (n)-[r]-()
                    WHERE type(r) <> 'RESOLVES_TO' AND coalesce(r.is_current, true) = true
                }
                RETURN count(n) AS count
                """
                result = session.run(protected_query)
                stats["protected_current_nodes"] = result.single()["count"]

                # 2. Delete forgotten nodes only when they are unrelated to every
                # active fact. A valid but seldom-mentioned family/job/etc. must
                # not disappear merely because its ranking score decayed.
                # 30 days in ms = 30 * 24 * 60 * 60 * 1000 = 2592000000
                forget_query = """
                MATCH (n:Entity) 
                WHERE n.importance < 0.2 
                AND n.updated_at < (timestamp() - 2592000000)
                AND NOT EXISTS {
                    MATCH (n)-[r]-()
                    WHERE type(r) <> 'RESOLVES_TO' AND coalesce(r.is_current, true) = true
                }
                DETACH DELETE n RETURN count(n) AS count
                """
                result = session.run(forget_query)
                stats["forgotten_nodes"] = result.single()["count"]
                
                # 3. Prune orphan nodes (no connections at all)
                prune_query = """
                MATCH (n:Entity) 
                WHERE NOT EXISTS { MATCH (n)-[r]-() WHERE type(r) <> 'RESOLVES_TO' }
                DETACH DELETE n RETURN count(n) AS count
                """
                result = session.run(prune_query)
                stats["pruned_orphans"] = result.single()["count"]
                session.run(
                    "MATCH (identity:EntityIdentity) "
                    "WHERE NOT (identity)-[:RESOLVES_TO]->() DETACH DELETE identity"
                )
                
                logger.info(f"Memory Consolidation Done: {stats}")
                return stats
        except Exception as e:
            logger.error(f"Error in consolidate_memory: {e}")
            return stats

# Global instance
neo4j_client = Neo4jService()
