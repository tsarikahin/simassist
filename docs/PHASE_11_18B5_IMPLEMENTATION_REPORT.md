# Phase 11.18B.5 implementation report

Completed 2026-11-15. Scope: modular instructions and dynamic tools for one
user-facing MAF agent. No Phase 11.18C, face-picking implementation, simulation
study, material, boundary-condition, or solver functionality was added.

## Audit and integration

- Installed Microsoft Agent Framework core is **1.26.0**, Python **3.14.3** on
  Windows. The dependency requirement is agent-framework-core>=1.26.0.
- The actual API is `Agent(client=..., instructions=..., tools=..., middleware=...)`.
  `Agent.run(messages, stream=True, options=...)` returns the existing response
  stream with get_final_response; Agent.close retains cleanup ownership.
- The original factory exposed 16 SimulationTools methods with an 8,577-byte
  monolithic prompt. All original tool schemas are preserved by a golden test.
- ChatExecution already owned request-scoped construction, durable begin/finish
  turn exclusion and replay, role-aware history, summaries, context budgeting,
  sync responses, SSE, cancellation, failure persistence, and cleanup. It still
  owns all of these. No second agent runtime or classifier call was introduced.
- ProjectContextRepository owns selected geometry/mesh, RemeshProposalStore owns
  chat-scoped pending settings, FileRepository enforces upload ownership, and
  existing tools/worker services retain argument, dependency and artifact checks.
- This checkout has no agent CAD surface-picking or face-query tools. The
  selections module exposes existing uploaded inspection plus accurate limits;
  it does not fabricate Phase 11.18B/11.18C tools.

## Changes by responsibility

| Files | Responsibility |
|---|---|
| backend/src/simassist/agents/context.py | Typed routing snapshot, validated project/chat ownership, current geometry/artifact and selected mesh linkage, hidden/stale state, chat proposals and uploaded-reference hints |
| backend/src/simassist/agents/router.py | Deterministic multi-label aliases, authoritative context, anaphora, confirmation replies, negative/status intent, unsupported capabilities and conservative clarification |
| backend/src/simassist/agents/registry.py | Typed tool factories, explicit dependencies and conditional workflow bridges, fixed-point resolution, stable names, deduplication, cycle/unknown/conflict failures |
| backend/src/simassist/agents/orchestrator.py | Request-specific instructions/tools/schemas, existing token estimator, clarification-only capability-miss helper, actual MAF function middleware telemetry |
| backend/src/simassist/agents/core_instructions.md and modules/*/instructions.md | Small common rules, workspace, geometry, meshing, CAD inspection, selection limits, and combined workflow instructions |
| backend/src/simassist/agents/simulation_agent.py | Existing factory with optional request composition; original imports and explicit all-tools construction remain available |
| backend/src/simassist/agents/tools/simulation_tools.py | Existing implementations retained; adds read-only list_project_jobs and execution-time rejection of hidden geometry/mismatched active artifact references |
| backend/src/simassist/api/routes/chat.py | Resolves/composes before existing context assembly; uses the same composition for actual binding and budget accounting; metadata-only setup/completion logs and observed provider usage |
| backend/src/simassist/projects/workspace.py | Bounded latest completed user-message query for routing; excludes active/failed/interrupted turns without reconstructing the whole chat again |
| backend/tests/unit/test_agent_modules.py | Routing corpus, registry, availability, scope, stale revisions, confirmation, history/budget, uploaded hints and safe-miss regressions |
| backend/tests/integration/test_modular_maf.py | Actual installed MAF/OpenAI tool loop over a mocked transport, both normal and streaming; rejects absent tools and verifies dependency-aware submissions |
| backend/tests/integration/test_chat_memory.py and test_file_upload.py | Retained API/SSE/memory/replay coverage with actual composition; private telemetry checks and modular uploaded STEP-to-mesh execution |
| scripts/benchmarks/agent_architecture.py and fixtures/* | Reproducible offline/live evaluation; frozen original instructions/schemas and 54 utterances with expected domains/tools |
| backend/src/simassist/agents/README.md | Module registration, safety boundaries, diagnostics and evaluation guide |
| docs/benchmarks/agent-1118b5*.json | Pre-refactor baseline, initial runs and final measured report |

Workspace is always available. Geometry-only requests omit mesh/import mutations;
mesh-only requests omit geometry creation; inspection-only requests omit import
and mesh mutations. Combined workflow methods are conditional bridge bundles.
Dependencies are expanded before binding and before budgeting. The broadest
combined request exposes 18 tools, including the two new core helpers; ordinary
requests expose 6–10 rather than the original fixed 16.

Fallback is deliberately **clarification with zero automatic retries/expansions**.
request_capability reports a miss and asks for the intended next supported action.
No historical or partially executed request is replayed. A clarified next user
turn is composed anew. Existing chat request IDs, turn exclusion and one-use
pending proposals remain responsible for replay and confirmation semantics.

## Regression and build results

Final backend result: **225 passed in 26.25 s** (original suite: 142 tests).
Coverage includes all 54 routing fixtures, required tool inclusion/exclusion,
registry invalid configurations, missing/stale/hidden/cross-project geometry,
selected-versus-latest meshes, pending confirmation isolation and single
submission, legacy chatless proposal scope, historical tool text, bounded long
chat summaries, uploaded metadata injection/scope, import/mesh dependency order,
sync/SSE event shapes, actual MAF streaming/tool binding, failure, cancellation,
cleanup, request replay and private diagnostics.

Commands used with the existing environment:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
.venv/Scripts/python.exe -m ruff check backend/ scripts/benchmarks/agent_architecture.py
.venv/Scripts/python.exe -m ruff format --check backend/ scripts/benchmarks/agent_architecture.py
.venv/Scripts/python.exe -m pytest backend/tests -q --basetemp .tmp/phase1118b5-release-tests -o cache_dir=.tmp/pytest-cache-1118b5 --tb=short
npm.cmd --prefix frontend run build
.venv/Scripts/python.exe scripts/benchmarks/agent_architecture.py --samples 30 --live
```

Ruff: **All checks passed; 119 files already formatted**. Frontend: TypeScript and
Vite production build passed, 2,599 modules transformed. Vite retains its existing
warning about the >500 kB bundle (1,293.69 kB before gzip); no frontend source or
SSE contract changes were needed.

The initial default pytest temporary-directory attempt hit sandbox permissions;
workspace-local temporary paths resolved it. uv's shared cache was also blocked,
so checks used the existing .venv directly. npm.cmd avoids this PowerShell host's
disabled npm.ps1 execution. Git operations/checks were initially skipped at the user's
request; a direct whitespace/conflict-marker check was used instead. The user
subsequently authorized committing the changes, enabling Git diff validation. Disposable
test/benchmark data is retained under the already-ignored .benchmarks directory.

## Baseline versus modular measurements

The pre-refactor capture is agent-1118b5-baseline.json. Frozen original prompt and
schemas are checked in, so the comparison does not reconstruct an approximation
of the old prompt from the new modules. Both sides use the same provider/model
and tool implementations. The offline setup comparison alternates mode order
and measures 30 repetitions of six fixed workloads (**180 samples per mode**).

| Metric | Monolithic | Modular |
|---|---:|---:|
| Instruction bytes, corpus mean | 8,577 | 3,999 |
| Schema bytes, corpus mean | 10,609 | 3,769 |
| Estimated instruction tokens | 2,871 | 1,345 |
| Estimated schema tokens | 3,549 | 1,269 |
| Combined estimated tokens | 6,420 | 2,614 (**59.3% less**) |
| Exposed tools, corpus mean | 16 | 8.98 |
| Setup median | 25.41 ms | 11.73 ms |
| Setup p95 | 63.08 ms | 30.93 ms |

Estimates use the existing UTF-8 bytes/3 + framing heuristic, not provider usage.
Combined instruction/schema overhead consumes about 39.2% versus 16.0% of the
default 16,384-token context window, before conversation/tool results. The setup
measurement includes schema generation, client/agent construction and, for the
modular side, routing/composition; it excludes inference and DB context reads.
Routing plus composition alone measured 5.47 ms median / 12.09 ms p95 over the
54 fixtures. Full live request timing includes validated context resolution.

Routing fixtures: **54/54 exact domain matches**, micro precision/recall **1.0**,
**zero missing required tools**, and **5/54 (9.26%) deliberate conservative
fallbacks**. These are curated English fixtures, not a population accuracy claim.
The baseline has no classifier; its static capability availability metrics in
the JSON are not baseline LLM routing accuracy. Actual tool selection was also
evaluated in the live comparison below.

### Real local model and worker comparison

Provider: local LM Studio-compatible endpoint on 127.0.0.1:1235, model
**spark-x2.6-4b**, temperature 0, max output 768 per model round. Each of six
workloads ran once in each mode, in alternating order, with fresh isolated
project/chat state, identical verified square/mesh fixtures and STEP uploads.
Requests execute the full MAF tool loop; afterwards the real worker drains jobs
and verifies completion. Fixture setup and worker drain are outside request time.

| Workload | Monolithic | Modular | Action result |
|---|---:|---:|---|
| Geometry creation | 7.279 s | 5.068 s | both correct |
| Existing geometry meshing | 24.733 s | 15.416 s | both correct |
| STEP inspection | 6.817 s | 6.137 s | both correct |
| Persisted confirmation | 10.621 s | 7.266 s | both correct |
| Combined geometry/mesh | 9.246 s | 11.448 s | both correct |
| Negative/status-only request | 11.202 s | 9.635 s | both correct |
| Mixed workload median | **9.933 s** | **8.450 s** | six samples per mode |

Both modes invoked the expected tools in **6/6** cases, created exactly **5**
intended jobs each, and completed all **5/5** with **zero duplicates or failures**.
Provider-reported aggregate input tokens across all model rounds were
**70,671 → 26,354**; output tokens were **2,723 → 2,031**. These observed totals
include repeated model rounds and tool results and must not be equated with the
initial-request heuristic estimates above.

Earlier runs were slower for the modular agent: medians 11.814 s versus 9.719 s
initially, and 11.129 s versus 8.401 s before response tuning. Both raw reports
are retained as agent-1118b5-initial.json and agent-1118b5-before-response-tuning.json.
We removed a redundant get_pending_remesh model round (confirm_remesh already
reads/validates the persisted proposal) and tightened default response length.
The final run is faster in five cases, but the combined case remains slower.
This small experiment supports footprint/setup gains and functional parity;
it does **not** establish a universal end-to-end speedup or a live p95. Model
output/reasoning length, caching, workload and warm-up affect these timings.

## Compatibility and remaining limits

- Existing routes, request/response/SSE shapes, project files, jobs, artifacts,
  geometry/mesh revisions, summaries and chat isolation are retained. No schema
  migration, new mandatory dependency or cloud service is required.
- The original factory/helper imports remain usable for explicit all-tools
  integrations. Production chat uses request-specific composition and counts
  exactly the selected schemas against its existing budget.
- The router uses curated English signals and bounded recent intent. Unfamiliar
  wording, ambiguous references and absent capabilities may need another user
  turn. Automatic capability expansion is intentionally disabled to avoid replay.
- Routing context validates stored job/revision linkage and hidden geometry.
  Tools revalidate at execution; physical artifact/native CAD/mesh verification
  still belongs to existing services and the worker, not routing heuristics.
- Context resolution still inspects project jobs for active-geometry mesh state;
  very large job collections may warrant a separately profiled indexed lookup.
- Legacy chatless calls retain project-scoped proposals and the existing absence
  of durable per-chat turn replay caching. The normal UI uses chat-scoped turns.
- Selection guidance accurately reports missing agent face-selection tools.
  Named regions, materials, BCs and solvers remain unavailable and unregistered.
- Full prompts, attachment content and tool arguments/results are excluded from
  the new diagnostics. Provider usage remains optional; estimates are labeled.

Registration instructions are in backend/src/simassist/agents/README.md. Suggested
commit: `refactor(agent): dynamically load domain tools and instructions`.
Git was initially skipped as requested; after implementation, the user explicitly
authorized committing these changes.
