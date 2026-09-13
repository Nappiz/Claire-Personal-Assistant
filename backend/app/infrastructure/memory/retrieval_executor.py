"""One shared retrieval pool; propagate request/turn context to each task."""
import concurrent.futures
from contextvars import copy_context


class RetrievalExecutor:
    def __init__(self, config, executor=None):
        self.executor = executor if executor is not None else concurrent.futures.ThreadPoolExecutor(
            max_workers=max(2, min(int(config.MEMORY_RETRIEVAL_WORKERS), 32)),
            thread_name_prefix="memory-retrieval")

    def submit(self, function, *args, **kwargs):
        return self.executor.submit(copy_context().run, function, *args, **kwargs)
