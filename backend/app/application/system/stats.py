from app.application.dependencies import ResourceDependencies
def get_system_stats(dependencies: ResourceDependencies):
    """Mendapatkan statistik sistem dari seluruh database"""
    stats = dependencies.uow.usage.stats()
    graph_stats = dependencies.graph.get_stats()
    vector_stats = dependencies.vector.get_stats()
    return {**stats, "graph_nodes": graph_stats.get("nodes", 0),
            "graph_edges": graph_stats.get("edges", 0),
            "vector_memories": vector_stats.get("vectors", 0)}
