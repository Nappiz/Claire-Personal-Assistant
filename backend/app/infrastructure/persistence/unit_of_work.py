from sqlalchemy.exc import IntegrityError
from app.application.errors import ApplicationError
from .projects import SQLAlchemyProjectRepository
from .conversations import SQLAlchemyConversationRepository
from .messages import SQLAlchemyMessageRepository
from .memory_jobs import SQLAlchemyMemoryJobRepository
from .settings import SQLAlchemySettingsRepository
from .usage import SQLAlchemyUsageRepository


class SQLAlchemyUnitOfWork:
    def __init__(self, db):
        self.db = db
        self.projects = SQLAlchemyProjectRepository(db)
        self.conversations = SQLAlchemyConversationRepository(db)
        self.messages = SQLAlchemyMessageRepository(db)
        self.jobs = SQLAlchemyMemoryJobRepository(db)
        self.settings = SQLAlchemySettingsRepository(db)
        self.usage = SQLAlchemyUsageRepository(db)

    def commit(self):
        self.db.commit()

    def commit_project(self, project):
        try:
            self.db.commit()
            self.db.refresh(project)
        except IntegrityError as exc:
            self.db.rollback()
            raise ApplicationError(409, "Project name already exists") from exc

    def rollback(self):
        self.db.rollback()

    def refresh(self, record):
        self.db.refresh(record)

    def close(self):
        self.db.close()
