"""Existing bounded in-process log sink."""
import logging
from collections import deque
from app.observability.correlation import CorrelationFilter

log_buffer = deque(maxlen=1000)

class MemoryHandler(logging.Handler):
    def emit(self, record):
        log_buffer.append(self.format(record))

def configure_logging():
    memory_handler = MemoryHandler()
    memory_handler.addFilter(CorrelationFilter())
    memory_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s request=%(request_id)s session=%(session_id)s turn=%(turn_id)s: %(message)s"))
    logging.getLogger().addHandler(memory_handler)
    logging.getLogger().setLevel(logging.INFO)
