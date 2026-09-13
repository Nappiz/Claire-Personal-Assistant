import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class GraphReads:
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
