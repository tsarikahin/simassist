# SimAssist — Phase 11.15: Agent Conversation Memory & Context Management

**Status:** Implementation specification for Codex  
**Priority:** High  
**Depends on:** Phase 11.13 (interactive remesh clarification), Phase 11.14 (persistent workspace and chats), Phase 11.14.1 (unified Geometry / Mesh explorer)  
**Primary goal:** Make each SimAssist chat a durable, isolated, token-budgeted conversation with **native role-aware agent history** instead of concatenating previous chat messages into a single text prompt.

> **Codex task:** Inspect the actual repository at HEAD before implementing. The source snapshot reviewed for this document included Phase 11.14, but the user's working tree also contains later Phase 11.14.1 frontend changes. Preserve all existing features, migrations, and data. Implement this phase incrementally, with tests. Do not assume Microsoft Agent Framework APIs without verifying the version installed in this repo.

## 1. Product intent

SimAssist is a **local-first AI engineering copilot**. It uses React/TypeScript + Vite + VTK.js in the frontend, FastAPI/Python in the backend, Microsoft Agent Framework (MAF) for agent execution, a configurable LLM provider (currently LM Studio via an OpenAI-compatible endpoint), Gmsh for geometry/meshing, and SQLite for persistent jobs, projects, chats, and context.

A user can create multiple projects and multiple chats within each project. Chats have independent conversation histories, but chats **within the same project intentionally share engineering state** (geometry, mesh jobs, artifacts). Active geometry and verified job results are authoritative in the backend, not in a language model's memory.

The agent should be aware of *what was discussed*, without treating historic text as new instructions or accidentally re-executing prior tool calls.

### Desired experience

Conversation in Chat A:

1. User: `Create a 2D annulus with inner radius 1 mm and outer radius 2 mm.`
2. Agent creates geometry via tool and returns job information.
3. User: `Mesh it with triangles, 0.05–0.1 mm.`
4. Agent consults **current project geometry state**, submits the correct mesh job, and reports status.
5. User: `Change the mesh to quads.`
6. Agent checks current mesh settings and, because mesh sizes were not specified, **asks a clarification question** rather than silently choosing settings (Phase 11.13).
7. User: `Keep existing sizes.`
8. Agent confirms the pending proposal associated with Chat A and submits **exactly one** mesh job.

At the same time, Chat B in the same project has its *own* messages and pending remesh proposal; Chat B cannot see Chat A's private conversation turns or confirm Chat A's proposal. Both may inspect the project's geometry/mesh artifacts using backend tools.

## 2. Baseline: what the current implementation does

The reviewed Phase 11.14 implementation contains:

- `backend/src/simassist/api/routes/chat.py`: `ChatRequest(project_id, chat_id?, message)`, `/api/chat`, `/api/chat/stream`; `_prompt()` fetches `WorkspaceRepository.messages(project_id, chat_id)[-16:]`, truncates each message to 2,500 characters, concatenates lines labeled `USER:` / `ASSISTANT:`, then appends `CURRENT USER REQUEST:`. This entire string is sent in a **single** `agent.run(prompt)` call.
- `backend/src/simassist/projects/workspace.py`: `WorkspaceRepository`, with `workspace_projects`, `workspace_chats`, `workspace_messages` in `jobs.db`. Messages currently have `id`, `chat_id`, `role`, `content`, `created_at`; `append()` permits `user` and `assistant` roles.
- `backend/src/simassist/agents/simulation_agent.py`: `build_simulation_agent()` creates a new MAF `Agent` with tools and static engineering instructions. The API closes the agent after the request.
- `backend/src/simassist/llm/factory.py`: provider abstraction; LM Studio uses `OpenAIChatCompletionClient`.
- `backend/src/simassist/api/routes/workspace.py`: project/chat list, create, rename, delete, and message-list endpoints.
- Existing synchronous and SSE streaming execution; the SSE contract uses `status`, `delta`, `jobs`, `done`, `error` events.
- Phase 11.13's persisted remesh proposals are scoped to chats when `chat_id` exists. Preserve that behavior.

**Problems to fix:** history roles are flattened into a text prompt; 16-message/2,500-character limits are arbitrary and insensitive to model context limits; intermediate tool invocations are not persisted as conversation history; long chats do not have durable summaries; current endpoint processing has no explicit concurrency policy for simultaneous requests to the same chat; failures and interrupted streams need clear persistence semantics.

## 3. Required scope (MVP for Phase 11.15)

### A. Role-aware model context

Implement a dedicated `ConversationContextService` (name flexible) that builds the model input from:

1. **Agent system instructions**, kept separate from user content.
2. **Optional concise summary** of older messages from this chat only.
3. **Recent complete conversation turns** with their actual `user` / `assistant` roles and chronological order.
4. **The current user message**, once, as the final user turn.

Do not format untrusted historical content as system instructions. Do not prepend all history into one user prompt. Use the supported MAF role-aware message/session/history mechanism for the **installed MAF version**. Check SDK/API signatures in the locked environment. If the chosen SDK feature is immature, use an adapter from persisted messages to the SDK's explicit message objects and document that choice.

Important: each API request may still create/close a fresh Agent instance. **Durable conversation memory must come from persisted, independently reconstructable chat state**, not an in-process singleton or dependence on a single live agent instance.

### B. Budgeted context selection

Replace the fixed `[-16:]` / `[:2500]` strategy with a configurable **context budget**:

- `SIMASSIST_CONTEXT_WINDOW_TOKENS`: effective model context limit, default conservative and local-model friendly (e.g. 4096; configurable).
- `SIMASSIST_RESPONSE_RESERVE_TOKENS`: reserve output tokens (e.g. 768 or as appropriate).
- `SIMASSIST_CONTEXT_SAFETY_MARGIN_TOKENS`: safety reserve for tools, serialization, and provider overhead.
- Budget must include system instructions, tool definitions/schema overhead, current user message, summary, and selected history; never fill the entire window with history.
- Use a provider/model tokenizer when reliable; otherwise a **documented conservative estimator** with measurable headroom. Don't claim estimates are exact token usage.
- Retain **complete turns**, avoid cutting a tool call away from its result or mixing unrelated requests.
- If the current request by itself exceeds the safe window, return a clear actionable error. Never silently truncate an engineering requirement.

An initial last-N-turns selection plus an approximate budget is acceptable if it actually honors the configured limit and is testable. Keep the budget policy modular so token counting can be improved later.

### C. Persistent conversation state, isolated by project and chat

Extend SQLite **additively**; no destructive migrations, no deleting existing rows or rewriting the jobs database.

At minimum maintain:

- Ordered user/assistant messages (the frontend-visible canonical record).
- Optional persisted summary per chat, with a **watermark** indicating which message IDs it covers.
- Version/state metadata needed to avoid summarizing the same messages repeatedly or accidentally dropping new turns.
- Optional execution metadata for a turn (request ID, started/completed/failed, time, token estimate, model/provider); avoid breaking existing message-list responses.

If storing tool-call traces now, keep them in **separate internal records** or a versioned event log rather than showing raw tool protocol messages in the chat UI. Never reveal secrets or sensitive tool input in logs or summaries. Explain schema changes in comments/docstrings.

**Chat deletion** must also delete (or explicitly invalidate) summary and chat-owned trace records, without deleting project geometry/artifacts. **New Chat** must have no memory inherited from another chat, except shared project state retrieved through tools.

### D. Rolling long-term summary

Add chat-local summarization when older turns no longer fit the context budget.

A good summary captures:

- User's enduring **engineering intent** within this specific chat.
- Decisions and explicit user approvals/rejections.
- Parameters/units **with provenance** and ambiguity markers.
- Job/artifact references **as references, not proof of current status**.
- Open questions, pending decisions, and constraints.

Guardrails:

- A summary is **untrusted context**, not authoritative engineering state.
- Never replace backend checks for active geometry, mesh parameters, verification results, or pending proposals with summary assertions.
- Never treat a summarized historical request as permission to create a job.
- Use a clear watermark for summarized message IDs, and do not duplicate the summary's turns in recent history.
- Prefer compact, structured text; establish a maximum summary size.
- If summarization fails or the local model is unavailable, **fall back gracefully** to recent history within the budget; do not fail a perfectly valid user request solely because summary generation failed.
- Avoid an extra LLM call on **every message**. Trigger summary only when context pressure justifies it; allow disabling automatic summarization for local CPU/low-VRAM usage.

### E. Tool-call and engineering-state safety

**Key principle: conversation memory remembers dialogue; backend services own engineering truth.**

- `get_active_geometry` and mesh/job lookup tools stay authoritative.
- Mesh inspection must not say `no mesh yet` merely because the present chat has never created a mesh; check project-level jobs/artifacts.
- A previous tool call mentioned in history must **never be re-executed** simply because it appears in context.
- Preserve explicit confirmation boundaries (e.g. `confirm_remesh` only when the **current** user message authorizes it).
- Keep pending clarification/remesh proposals scoped to the correct `chat_id` and validated against current active geometry.
- If tool traces are used in model context, preserve valid call/result pairing and order; never insert an orphaned tool result. If the provider/MAF adapter does not support replaying traces safely, **do not replay them in the MVP**; keep a human-readable verified event summary instead.
- Existing mesh versioning is append-only. Do not delete old mesh versions when remeshing.

### F. Sync + streaming behavior

Maintain both `POST /api/chat` and `POST /api/chat/stream`, and the existing SSE event names/payloads used by the frontend. Ensure both routes use **exactly the same context assembly and persistence policy**.

- Store a user turn exactly once for each accepted request, with a stable request/turn identifier if practical.
- Store only the **final committed assistant response** in the canonical chat history, not every streamed delta.
- Define what happens when streaming disconnects, the tool submits a job but the assistant fails, a request is retried, or the model errors; avoid phantom `completed` turns and accidental duplicate job execution.
- Add per-chat concurrency protection (queue/lock or explicit `409 Conflict`) so simultaneous requests cannot read/write divergent history. Do not serialize independent chats unnecessarily.
- Prefer idempotency keys for submission endpoints when feasible; if not included in MVP, make duplicate-job risk explicit and test the chosen failure behavior.
- Maintain readable error messages and close agent resources on all paths.

### G. Observability and debugging

Log or expose (through structured debug logs or a lightweight diagnostic endpoint, not necessarily a UI change):

- `project_id`, `chat_id`, request/turn ID; provider/model.
- Number of loaded recent turns and summary watermark.
- Approximate context tokens vs configured budget.
- Summarization triggered/skipped/failed.
- Whether a tool/job submission occurred.

Do not log full user conversation content, secrets, or private files by default. Keep any diagnostic API off or restricted by configuration.

## 4. Suggested module layout (adapt to repo)

```text
backend/src/simassist/
  conversations/
    context_service.py       # assemble role-aware context
    budget.py                # token budget / turn selection
    summary.py               # optional incremental summarization
    models.py                # domain DTOs / persisted metadata
  projects/
    workspace.py             # additive SQLite migrations/repository methods
  api/routes/
    chat.py                  # sync/SSE orchestration; no prompt concatenation
  agents/
    simulation_agent.py      # agent construction, MAF message/session integration
  llm/
    factory.py               # provider capability considerations
backend/tests/
  unit/test_conversation_context.py
  unit/test_conversation_budget.py
  unit/test_conversation_summary.py
  integration/test_chat_memory.py
```

Use existing conventions instead of forcing this exact tree if the repository has evolved.

## 5. Suggested implementation order

1. **Review repository + MAF SDK installed version.** Document supported role/session/message interfaces and inspect existing workspace/chat logic.
2. **Introduce conversation DTOs and context builder.** Unit-test ordering, isolation, and absence of duplicate current message.
3. **Switch both chat endpoints to role-aware input**, keeping the SSE contract unchanged and no automatic summary yet.
4. **Introduce configurable budget/turn selection**, including fallback estimator.
5. **Add additive summary storage and watermark**, then summary-on-pressure with graceful fallback.
6. **Define persistence failure/retry/concurrency semantics** and add tests.
7. **Add diagnostic metadata** and regression tests for geometry context and remesh confirmations.
8. Run test/build/lint and write a short migration/implementation note.

## 6. Acceptance criteria — must pass

- [ ] Chat A history is never supplied to Chat B's model input, even in the same project.
- [ ] Chat B can still inspect the current project's geometry/mesh through tools.
- [ ] User/assistant turns enter MAF as **distinct roles**, not one concatenated string.
- [ ] A fresh backend process restores the same conversation context from SQLite.
- [ ] Existing messages from Phase 11.14 remain readable (no data loss).
- [ ] A new empty chat starts with no inherited conversation summary.
- [ ] The context budget is configurable and measured; long chats are truncated/summarized by **whole turns**, not arbitrary character slicing.
- [ ] Summary watermark prevents message overlap; failed summarization falls back safely.
- [ ] Sync and SSE routes produce consistent persistence; streaming deltas are not stored as duplicate assistant messages.
- [ ] Deleted chats cannot be reopened through their IDs or retain orphaned summaries.
- [ ] Two concurrent requests to the same chat cannot corrupt history; independent chats work concurrently.
- [ ] Past tool calls are not replayed merely by loading their records.
- [ ] The Phase 11.13 clarify → confirm flow creates **zero jobs before confirmation** and **one job after valid confirmation**.
- [ ] A chat asking about an existing mesh returns counts from backend job/artifact records rather than hallucinating `no mesh yet`.
- [ ] Backend tests pass, frontend build passes, and current Geometry/Mesh explorer remains functional.

### Suggested test scenarios

| Scenario | Expected |
|---|---|
| A: user creates geometry; later says `mesh it` | Resolve active project geometry through tool, not from potentially stale memory |
| A: chat discusses 100+ messages | Bounded context + appropriate summary; no context-window overflow |
| A: pending remesh; B: `yes` | B does not confirm A's proposal |
| SSE response split over many deltas | Exactly one assistant message saved on successful completion |
| Invalid chat ID/project pairing | Reject with 404/validation error, never fall back to another chat |
| History contains `delete all geometries` as a quote | No deletion triggered from historical context |
| Selected mesh in viewer differs from latest completed mesh | Agent discloses which mesh it actually used; do not pretend the selection is already synchronized |
| Small local model with limited context | Controlled budget and graceful summary fallback |

## 7. Non-goals for Phase 11.15

- No vector database, embeddings, RAG, or cross-chat semantic search yet.
- No shared user profile or cross-project long-term memory.
- No automatic geometry selection based solely on chat text.
- No new solver, FEM physics, mesh generation algorithms, or VTK changes.
- No requirement to replay raw tool-call traces to the LLM if this is unsupported/unsafe.
- No silent changes to geometry/artifact storage or irreversible data migration.

## 8. Developer commands (adapt to repo environment)

```powershell
uv run --package simassist-backend pytest backend/tests -q
npm --prefix frontend run build
git diff --check
git status
```

If Ruff is configured, also run its check/format validations. Keep Windows/PowerShell compatibility. Backend and worker restart guidance should accurately reflect files changed.

## 9. Final Codex deliverables

1. Working implementation committed as reviewable changes, not an unreviewed architectural rewrite.
2. SQLite additive migration and tests.
3. Config documentation for context limits, reserve, and summary behavior.
4. Short description of MAF integration choice **with verified installed SDK API**.
5. Test outcomes and outstanding risks, especially streaming interruption and local-model token estimates.
6. Updated user-facing documentation explaining chat independence versus shared project state.

**Guiding rule:** A remembered conversation is not a simulation result. Verified engineering data must always come from backend tools and artifacts.
