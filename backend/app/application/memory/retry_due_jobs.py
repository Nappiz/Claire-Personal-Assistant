from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from app.domain.memory.contracts import MEMORY_JOB_LEASE_SECONDS
logger = logging.getLogger("services.memory_service")

class RetryDueJobs:
    def process_due_memory_jobs(self, limit: int = 25) -> list[dict]:
        """Retry durable jobs after a restart or exponential-backoff delay."""

        safe_limit = min(max(int(limit), 1), 100)
        now = datetime.now(timezone.utc)
        legacy_lease_expired_at = now - timedelta(seconds=MEMORY_JOB_LEASE_SECONDS)
        db = self.persistence.open()
        try:
            job_ids = [
                row[0]
                for row in db.process_due_memory_jobs_job_ids(legacy_lease_expired_at, now, safe_limit)
            ]
        finally:
            db.close()

        results = []
        for job_id in job_ids:
            try:
                result = self.process_memory_job(job_id)
                if result:
                    results.append(result)
            except Exception:
                logger.exception("Unexpected failure while retrying memory job %s", job_id)
        return results

    def list_memory_jobs(self, limit: int = 50) -> list[dict]:
        """List job health for an authenticated operator without exposing messages."""

        safe_limit = min(max(int(limit), 1), 100)
        db = self.persistence.open()
        try:
            jobs = (
                db.list_memory_jobs_jobs(safe_limit)
            )
            return [self.outbox.outbox_job_data(job) for job in jobs]
        finally:
            db.close()

    def retry_memory_job(self, job_id: str) -> dict | None:
        """Make an unfinished job eligible for immediate processing again."""

        db = self.persistence.open()
        try:
            job = db.retry_memory_job_job(job_id)
            if not job:
                return None
            if job.status in {"completed", "cancelled"}:
                raise ValueError(f"Cannot retry a {job.status} memory job")
            if job.status == "processing" and job.lease_expires_at:
                lease_expires_at = job.lease_expires_at
                if lease_expires_at.tzinfo is None:
                    lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
                if lease_expires_at > datetime.now(timezone.utc):
                    raise ValueError("Cannot retry a memory job with an active lease")
            elif job.status == "processing":
                updated_at = job.updated_at
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                if updated_at > datetime.now(timezone.utc) - timedelta(seconds=MEMORY_JOB_LEASE_SECONDS):
                    raise ValueError("Cannot retry a recently processing memory job")
            job.status = "pending"
            job.next_retry_at = datetime.now(timezone.utc)
            job.last_error = None
            job.lease_token = None
            job.lease_expires_at = None
            db.commit()
            db.refresh(job)
            return self.outbox.outbox_job_data(job)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
