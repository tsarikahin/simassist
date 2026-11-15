# Conversation memory (Phase 11.15)

Each chat has independent messages and memory. Chats in the same project share
geometry, meshes and artifacts through backend tools. Starting a new chat does
not copy another chat's dialogue. Current geometry selection, latest completed
mesh, verification results and pending remesh proposals remain backend truth.
On page load, SimAssist reuses the newest empty **Untitled Project** before
creating another. Automatically created chats without messages count as empty;
projects containing messages, jobs or geometry references are preserved.
**+ Project** always creates a new project. To name the selected project, click
the pencil beside the project selector, enter a name, then click **Save**.
The trash button beside the selector deletes the selected project and all its
chat histories and memory after confirmation. Job records and simulation files
remain on disk. Active or unreconciled chat requests block deletion. The app
opens another project afterwards, or an empty untitled project if none remain.
The **Legacy** button can explicitly reimport retained demo engineering jobs;
deleted conversations are not restored.
Viewer mesh selection is not yet synchronized to the agent; mesh inspection
uses the latest completed mesh of the active geometry and discloses that source.

## SDK integration

Verified locally against installed `agent-framework-core==1.26.0`:
`Message(role, contents)` and `Agent.run(messages, stream=False, options=...)`
accept explicit user/assistant messages. The adapter reconstructs these on each
request, while `Agent(instructions=...)` retains separate system instructions.
No live session singleton is needed. Raw tool calls/results are neither stored
nor replayed. Internal turn metadata stores submitted job IDs, not tool inputs.
`tool(fn).to_json_schema_spec()` accounts for the same schemas supplied to the
agent; `options={'max_tokens': ...}` applies the response reserve.

## Configuration

Set these environment variables before starting the API:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `SIMASSIST_CONTEXT_WINDOW_TOKENS` | 16384 | Effective context limit; must match the loaded model |
| `SIMASSIST_RESPONSE_RESERVE_TOKENS` | 768 | Reserved and requested maximum output tokens |
| `SIMASSIST_CONTEXT_SAFETY_MARGIN_TOKENS` | 1536 | Headroom for tool results, protocol and estimation error |
| `SIMASSIST_SUMMARY_MAX_TOKENS` | 512 | Maximum estimated size of summary including its wrapper |
| `SIMASSIST_AUTO_SUMMARY` | true | Set false to disable automatic summary updates |

Token counts are estimates: ceil(UTF-8 bytes / 3), plus 12 per message/schema
block. This overestimates typical English but is not a tokenizer guarantee for
all languages or models. System instructions, serialized tool schemas, summary,
whole recent exchanges and the current message are counted. The current request
is never sliced. An input that cannot fit returns HTTP 422 with configuration
guidance. The full tool surface alone plus instructions is approximately 5200
estimated tokens, so a 4096-token model cannot support this tool surface safely.
Defaults therefore use 16384; do not advertise a larger window than your model
actually supports. Large in-flight tool results can consume more than the safety
reserve; provider overflow fails the turn without committing assistant text.

Summaries are bounded, structured JSON excerpts with message IDs and speaker
provenance, explicitly labeled untrusted. They preserve whole exchanges,
prioritizing the initial intent and recent decisions that fit. Oversize exchanges
are omitted; parameters and units in retained exchanges are copied verbatim.
These are deliberately lossy summaries, not inferred engineering facts. Obvious
credential-bearing exchanges are excluded by a keyword filter; this is not a
complete secret detector. Canonical chat messages remain unchanged. No extra LLM
call is made, and no raw tool payloads/private files enter the summary. Pressure
triggers incremental updates; an exclusive watermark prevents overlap with
recent history. Failed updates fall back to bounded recent context. Disabling
automatic summaries leaves existing stored memory readable but stops updates.

## Persistence, concurrency and retries

The repository adds `conversation_summaries` and `conversation_turns` and indexes
using `CREATE ... IF NOT EXISTS`. Existing message and job schemas/rows remain
unchanged. No database replacement or destructive migration is required.
Deleting an idle chat removes its messages, summaries and internal turns;
project engineering artifacts are preserved. Busy chats return HTTP 409 on delete.

Both routes share the same execution lifecycle. SQLite's transaction and partial
unique index allow one started turn per chat, across API processes; independent
chats can execute concurrently. Accepted requests append one user message.
Only a successful final response appends an assistant message, once. Failed or
interrupted user messages remain visible but are excluded from future model
context. Partial SSE deltas never enter canonical history. Cancellation closes
the agent and marks the turn interrupted. Jobs already submitted keep running.

Clients may provide a UUID `request_id` (the frontend supplies one per send).
Retries must reuse that ID, chat and exact message. Completed turns return the
stored response/jobs, including a `done` event on SSE replay. Active, failed,
interrupted or conflicting IDs return HTTP 409; they never rerun tools. Legacy
requests without `chat_id` remain stateless and have no durable retry protection.
A new request ID can repeat a job: inspect Project Explorer/Job Monitor before
retrying a failed or interrupted operation. Tool submission and SQLite turn
completion are not one atomic transaction.

A hard process crash leaves a `started` record and intentionally blocks that
chat rather than guessing whether a job was submitted. Reconcile project jobs
first. An operator can inspect metadata without reading dialogue:

```sql
SELECT request_id, chat_id, status, started_at, finished_at, job_ids
FROM conversation_turns WHERE status = 'started';
```

After stopping the API and verifying no request is active, mark only the
identified request `interrupted` using `WorkspaceRepository.finish_turn` with
verified job IDs. Restart the API afterwards. This is a manual recovery step;
there is no automatic timeout that might release a still-running operation.

Structured logs contain project/chat/request IDs, provider/model, recent turn
count, summary watermark/status, estimated tokens/budget and submitted job IDs.
They do not log dialogue or provider exception messages by default. No diagnostic
HTTP endpoint is exposed. Restart the API for code/environment changes; no worker
restart is needed for this phase.
