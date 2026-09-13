from app.application.dependencies import ResourceDependencies
from app.application.errors import ApplicationError
def get_projects(dependencies: ResourceDependencies):
    uow = dependencies.uow
    projects = uow.projects.list()
    return [
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "session_count": sum(1 for item in project.conversations if item.deleted_at is None),
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
        for project in projects
    ]

def create_project(request, dependencies: ResourceDependencies):
    uow = dependencies.uow
    name = " ".join(request.name.split())
    project = uow.projects.new(name=name, description=(request.description or "").strip() or None)
    uow.commit_project(project)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "session_count": 0,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }

def update_project(project_id, request, dependencies: ResourceDependencies):
    uow = dependencies.uow
    project = uow.projects.get(project_id)
    if project is None:
        raise ApplicationError(status_code=404, detail="Project not found")
    updates = request.model_dump(exclude_unset=True)
    if "name" in updates:
        project.name = " ".join(updates["name"].split())
    if "description" in updates:
        project.description = (updates["description"] or "").strip() or None
    uow.commit_project(project)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "session_count": len(project.conversations),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }

def delete_project(project_id, dependencies: ResourceDependencies):
    uow = dependencies.uow
    project = uow.projects.get(project_id)
    if project is None:
        raise ApplicationError(status_code=404, detail="Project not found")
    if any(item.deleted_at is None for item in project.conversations):
        raise ApplicationError(
            status_code=409,
            detail="Delete or move every session in this project first",
        )
    uow.projects.delete(project)
    uow.commit()
    return {"message": "Project deleted"}
