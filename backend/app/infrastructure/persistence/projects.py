from models.project import Project


class SQLAlchemyProjectRepository:
    def __init__(self, db):
        self.db = db

    def get(self, project_id):
        return self.db.get(Project, project_id)

    def list(self):
        return self.db.query(Project).order_by(Project.updated_at.desc()).all()

    def new(self, **values):
        project = Project(**values)
        self.db.add(project)
        return project

    def delete(self, project):
        self.db.delete(project)
