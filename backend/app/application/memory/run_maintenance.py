"""Scheduled graph consolidation with injected persistence and graph operations."""
from datetime import datetime, timezone

def run_memory_maintenance_once(session_factory, get_setting, set_setting, graph, logger) -> None:
    db = session_factory()
    try:
        last_run_str = get_setting(db, "last_consolidation_time")
        now = datetime.now(timezone.utc)
        if last_run_str:
            last_run = datetime.fromisoformat(last_run_str)
            time_diff = (now - last_run).total_seconds()
            if time_diff < 86400:
                return
            days_passed = time_diff / 86400.0
        else:
            days_passed = 1.0
        logger.info("Running scheduled memory consolidation (days=%s)", days_passed)
        graph.consolidate_memory(days_passed=days_passed)
        set_setting(db, "last_consolidation_time", now.isoformat())
    finally:
        db.close()
