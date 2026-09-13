from app.application.dependencies import ResourceDependencies
from app.application.errors import ApplicationError
def get_memory_jobs(limit, dependencies: ResourceDependencies):
    """Inspect durable memory jobs without returning their chat payload."""
    memory_service = dependencies.memory
    return {"jobs": memory_service.list_memory_jobs(limit=limit)}

def retry_memory_job(job_id, background_tasks, dependencies: ResourceDependencies):
    """Retry an unfinished memory job from its durable SQLite source event."""
    memory_service = dependencies.memory
    try:
        job = memory_service.retry_memory_job(job_id)
    except ValueError as exc:
        raise ApplicationError(status_code=409, detail=str(exc)) from exc
    if not job:
        raise ApplicationError(status_code=404, detail="Memory job not found")
    background_tasks.add_task(memory_service.process_memory_job, job_id)
    return {"message": "Memory job retry scheduled", "job": job}
