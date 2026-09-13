from types import SimpleNamespace as NS
from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.dependencies import ResourceDependencies
from app.application.projects.operations import create_project
from app.infrastructure.persistence.unit_of_work import SQLAlchemyUnitOfWork
from models import Base
from models.memory_outbox import MemoryOutbox


class RepositoryBoundaryTests(TestCase):
    def test_project_use_case_accepts_provider_free_fake_unit_of_work(self):
        records = []

        def new(**values):
            row = NS(id="fake", created_at=None, updated_at=None, **values)
            records.append(row)
            return row

        uow = NS(projects=NS(new=new), commit_project=lambda _: None)
        result = create_project(NS(name=" A   Project ", description=" "), ResourceDependencies(uow, None, None, None))
        self.assertEqual("A Project", result["name"])
        self.assertIsNone(records[0].description)

    def test_repositories_share_transaction_and_job_storage(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with sessionmaker(bind=engine)() as db:
                uow = SQLAlchemyUnitOfWork(db)
                project = uow.projects.new(name="Stored")
                uow.commit_project(project)
                conversation = uow.conversations.new(title="Conversation", project_id=project.id)
                uow.commit()
                job = MemoryOutbox(conversation_id=conversation.id, user_message="Assertion", assistant_response="Reply")
                db.add(job)
                uow.commit()
                self.assertEqual(job.id, uow.jobs.recent()[0].id)
                self.assertEqual(job.id, uow.jobs.get(job.id).id)
                uow.settings.set("theme", "dark")
                self.assertEqual("dark", uow.settings.get("theme"))
                uow.jobs.delete_for_conversation(conversation.id)
                uow.rollback()
                self.assertIsNotNone(uow.jobs.get(job.id))
        finally:
            engine.dispose()
