# Operational telemetry contract

New metadata events use operational_events.emit_event and a fixed allowlist.
No prompt, memory content, API key, page body, query text, or lease token is
added to these events. Logging failure is best-effort and cannot fail a response.

| Metadata | Owner/source |
| --- | --- |
| request_id/session_id/turn_id | CorrelationMiddleware + application_wiring; AI job context supplies session/turn when autonomous |
| invocation ID, provider/model, purpose | Existing ai_telemetry provider-call accounting |
| prompt version | domain/llm/prompt_versions; metadata only, transmitted prompt bytes unchanged |
| latency, tokens, finish status | Existing monotonic measurement and raw provider usage, before gateway normalization |
| token/cost unavailable | Remains unknown/null; never fabricate zero or a price |
| retrieval candidate IDs | BoundMemoryWorkflows logs returned vector source message IDs, not content |
| tool usage | WebWorkflowGateway logs tool type, status and result count, not URLs/query/body |
| job state | API workflow adapter + in-process due-job composition logs ID/status/session/turn |

Request IDs are runtime log correlation, not a new database column.
Autonomous retries cannot recover a historical request ID that was never
persisted; session/turn/job IDs remain the durable join keys. Existing logs and
AIInvocation schema/accounting behavior are unchanged by this extraction.
Cancellation drains coroutine tasks, but Python cannot force-stop a function
already running in an executor thread. Existing leases, tombstones, and
compensation remain the safety mechanisms for those writes.
