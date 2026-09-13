from app.application.dependencies import ResourceDependencies
from app.application.errors import ApplicationError
def _model_updates(request_model) -> dict:
    if hasattr(request_model, "model_dump"):
        return request_model.model_dump(exclude_unset=True)
    return request_model.dict(exclude_unset=True)
def get_knowledge_graph(limit, include_inactive, dependencies: ResourceDependencies):
    """Mendapatkan data nodes dan edges dari Neo4j untuk visualisasi 2D"""
    neo4j_client = dependencies.graph
    return neo4j_client.get_graph_data(limit=limit, include_inactive=include_inactive)

def delete_graph_node(entity_key, dependencies: ResourceDependencies):
    """Hapus satu entity secara presisi beserta relasinya."""
    neo4j_client = dependencies.graph
    deleted = neo4j_client.delete_node(entity_key)
    if not deleted:
        raise ApplicationError(status_code=404, detail="Graph node not found")
    return {"message": "Graph node deleted", "deleted": deleted}

def update_graph_node(entity_key, request, dependencies: ResourceDependencies):
    """Koreksi nama, konteks identitas, atau importance satu entity."""
    neo4j_client = dependencies.graph
    try:
        updated = neo4j_client.update_node(entity_key, _model_updates(request))
    except ValueError as exc:
        status_code = 409 if "already exists" in str(exc) else 400
        raise ApplicationError(status_code=status_code, detail=str(exc)) from exc
    if not updated:
        raise ApplicationError(status_code=404, detail="Graph node not found")
    return updated

def delete_graph_fact(fact_id, dependencies: ResourceDependencies):
    """Hapus satu fakta/edge tanpa menghapus entity di kedua ujungnya."""
    memory_service = dependencies.memory
    neo4j_client = dependencies.graph
    deleted = neo4j_client.delete_fact(fact_id)
    if not deleted:
        raise ApplicationError(status_code=404, detail="Graph fact not found")
    set_memories_status = dependencies.vector.set_memories_status
    source_ids = deleted.get("source_message_ids") or []
    memory_service.set_source_messages_memory_status(source_ids, "inactive")
    set_memories_status(source_ids, status="inactive")
    return {"message": "Graph fact deleted", "deleted": deleted}

def update_graph_fact(fact_id, request, dependencies: ResourceDependencies):
    """Aktif/nonaktifkan atau koreksi importance satu fakta."""
    memory_service = dependencies.memory
    neo4j_client = dependencies.graph
    try:
        updated = neo4j_client.update_fact(fact_id, _model_updates(request))
    except ValueError as exc:
        raise ApplicationError(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise ApplicationError(status_code=404, detail="Graph fact not found")
    if request.is_current is not None:
        set_memories_status = dependencies.vector.set_memories_status
        source_ids = updated.get("source_message_ids") or []
        memory_service.set_source_messages_memory_status(
            source_ids, "active" if request.is_current else "inactive"
        )
        set_memories_status(
            source_ids,
            status="active" if request.is_current else "inactive",
        )
    return updated
