from models.project import Project

class ResolveProjectScopeQueries:
    def resolve_project_scope_projects(self):
        return (self.db.query(Project).order_by(Project.updated_at.desc()).all())
