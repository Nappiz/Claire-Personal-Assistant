"""Compatibility facade; remove after legacy consumers migrate in stage 8."""
from app.compatibility import install_facade
from app.infrastructure.graph import neo4j_graph_store, neo4j_client_factory
install_facade(__name__, {
    "Neo4jService": (neo4j_graph_store, "Neo4jGraphStore"),
    "neo4j_client": (neo4j_graph_store, "graph_store"),
    "GraphDatabase": (neo4j_client_factory, "GraphDatabase"),
    "settings": (neo4j_client_factory, "settings"),
})
