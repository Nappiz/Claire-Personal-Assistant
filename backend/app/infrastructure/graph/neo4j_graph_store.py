from app.domain.graph.identity import EntityIdentityPolicy
from .neo4j_client_factory import Neo4jConnection
from .graph_writes import GraphWrites
from .graph_reads import GraphReads
from .graph_mutations import GraphMutations
from .provenance import GraphProvenance
from .consolidation import GraphConsolidation

class Neo4jGraphStore(EntityIdentityPolicy, GraphWrites, GraphReads, GraphMutations,
                      GraphProvenance, GraphConsolidation, Neo4jConnection):
    """GraphStore implementation, composed from cohesive transaction operations."""

graph_store = Neo4jGraphStore()
