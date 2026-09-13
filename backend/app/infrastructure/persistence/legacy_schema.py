"""Preserved local legacy repair; retirement plan lives in Analysis."""
from sqlalchemy import inspect, text

def ensure_local_legacy_schema(engine) -> None:
    """Upgrade legacy local SQLite databases created before Alembic tracking."""
    if engine.dialect.name != "sqlite":
        return
    message_columns = {column["name"] for column in inspect(engine).get_columns("messages")}
    conversation_columns = {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }
    outbox_columns = {
        column["name"] for column in inspect(engine).get_columns("memory_outbox")
    }
    with engine.begin() as connection:
        if "message_type" not in message_columns:
            connection.execute(
                text(
                    "ALTER TABLE messages ADD COLUMN message_type "
                    "VARCHAR(30) NOT NULL DEFAULT 'normal'"
                )
            )
        if "error_details" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN error_details JSON"))
        if "turn_id" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN turn_id VARCHAR(36)"))
        if "turn_sequence" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN turn_sequence INTEGER"))
        if "response_status" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN response_status VARCHAR(20) NOT NULL DEFAULT 'complete'"))
        if "finish_reason" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN finish_reason VARCHAR(50)"))
        if "memory_status" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN memory_status VARCHAR(20) NOT NULL DEFAULT 'active'"))
        if "is_pinned" not in conversation_columns:
            connection.execute(
                text(
                    "ALTER TABLE conversations ADD COLUMN is_pinned "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "pinned_at" not in conversation_columns:
            connection.execute(
                text("ALTER TABLE conversations ADD COLUMN pinned_at DATETIME")
            )
        if "project_id" not in conversation_columns:
            connection.execute(
                text("ALTER TABLE conversations ADD COLUMN project_id VARCHAR(36)")
            )
        for column_name, definition in (
            ("summary_version", "INTEGER NOT NULL DEFAULT 0"),
            ("summary_through_sequence", "INTEGER NOT NULL DEFAULT 0"),
            ("summary_pending", "BOOLEAN NOT NULL DEFAULT 0"),
            ("next_turn_sequence", "INTEGER NOT NULL DEFAULT 1"),
            ("active_turn_id", "VARCHAR(36)"),
            ("active_turn_expires_at", "DATETIME"),
            ("deleted_at", "DATETIME"),
        ):
            if column_name not in conversation_columns:
                connection.execute(text(f"ALTER TABLE conversations ADD COLUMN {column_name} {definition}"))
        if "project_id" not in outbox_columns:
            connection.execute(
                text("ALTER TABLE memory_outbox ADD COLUMN project_id VARCHAR(36)")
            )
        if "project_name" not in outbox_columns:
            connection.execute(
                text("ALTER TABLE memory_outbox ADD COLUMN project_name VARCHAR(120)")
            )
        if "scope" not in outbox_columns:
            connection.execute(
                text(
                    "ALTER TABLE memory_outbox ADD COLUMN scope "
                    "VARCHAR(20) NOT NULL DEFAULT 'global'"
                )
            )
        for column_name, definition in (
            ("lease_token", "VARCHAR(36)"),
            ("lease_expires_at", "DATETIME"),
            ("event_at", "DATETIME"),
        ):
            if column_name not in outbox_columns:
                connection.execute(text(f"ALTER TABLE memory_outbox ADD COLUMN {column_name} {definition}"))
        connection.execute(text("UPDATE memory_outbox SET event_at = created_at WHERE event_at IS NULL"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_conversations_project_id "
                "ON conversations (project_id)"
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_turn_id ON messages (turn_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_turn_sequence ON messages (turn_sequence)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_memory_status ON messages (memory_status)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_message_turn_role ON messages (conversation_id, turn_id, role)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_active_turn_id ON conversations (active_turn_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_active_turn_expires_at ON conversations (active_turn_expires_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_deleted_at ON conversations (deleted_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_outbox_lease_token ON memory_outbox (lease_token)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_outbox_lease_expires_at ON memory_outbox (lease_expires_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_outbox_event_at ON memory_outbox (event_at)"))

        legacy_rows = connection.execute(
            # SQLite rowid preserves legacy insertion order when timestamps tie;
            # UUID lexical order is unrelated to conversation chronology.
            text("SELECT id, conversation_id, role FROM messages WHERE turn_sequence IS NULL ORDER BY conversation_id, created_at, rowid")
        ).fetchall()
        counters: dict[str, int] = {}
        roles_in_turn: dict[str, int] = {}
        for message_id, conversation_id, role in legacy_rows:
            current = counters.get(conversation_id, 1)
            position = roles_in_turn.get(conversation_id, 0)
            # A second user starts another turn, rather than becoming the
            # presumed assistant half of a blind two-row pairing.
            if role == "user" and position:
                current += 1
                position = 0
            connection.execute(
                text("UPDATE messages SET turn_sequence = :sequence WHERE id = :message_id"),
                {"sequence": current, "message_id": message_id},
            )
            if role == "assistant":
                counters[conversation_id] = current + 1
                roles_in_turn[conversation_id] = 0
            else:
                counters[conversation_id] = current
                roles_in_turn[conversation_id] = 1
        for conversation_id, next_sequence in counters.items():
            connection.execute(
                text("UPDATE conversations SET next_turn_sequence = MAX(next_turn_sequence, :next_sequence) WHERE id = :conversation_id"),
                {"next_sequence": next_sequence + (1 if roles_in_turn.get(conversation_id) else 0), "conversation_id": conversation_id},
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_memory_outbox_project_id "
                "ON memory_outbox (project_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_memory_outbox_scope "
                "ON memory_outbox (scope)"
            )
        )
