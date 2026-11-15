# Request-scoped agent modules

ChatExecution remains the sole sync/SSE runtime. It validates attachment ownership
and durable turn identity, resolves a RoutingContext, composes instructions and
tools, then uses the existing ConversationContextService and MAF Agent lifecycle.
No router invokes a model or submits a job. Tool availability grants no authority.

## Registering a capability

1. Implement typed methods in the existing deterministic service/tool layer. Keep
   ownership, immutable revision checks, argument validation, and job dependencies
   there. Do not copy services or move working tools just to create a bundle.
2. Add `modules/<domain>/instructions.md`. Include only domain conventions. Core
   instructions own history trust, authorization, clarification, and status rules.
   Package resources use importlib.resources and ship with the backend package.
3. Register an AgentModule in registry.py with `bundle("method_name", ...)` or a
   typed ToolFactory, plus explicit dependencies. Stable callable names are the
   public MAF tool names. Identical bound methods deduplicate; different callables
   with the same name fail binding. Unknown dependencies and cycles fail registry
   construction. Add the domain to router signals only when its backend exists.
4. For a tool needed only by a combined workflow, register a bridge module with
   `include_when=("domain_a", "domain_b")` and explicit dependencies. Resolution
   expands dependencies and bridges to a fixed point in deterministic order.
5. Extend scripts/benchmarks/fixtures/agent_routing.json with expected domain sets,
   required tool names, and relevant context. Test both tool presence and absence,
   execution validation, history isolation, and real MAF streaming/binding. Run
   the benchmark against the frozen pre-phase instructions and schemas.

Workspace capabilities and the clarification-only request_capability helper are
always available. The helper distinguishes loaded, supported-but-unloaded, and
unknown domain labels, accepting operation aliases such as remeshing. Unknown
labels are not proof of a product limitation. It never loads tools, executes jobs
or retries anything. Missing capabilities take a clarified next turn, which is
routed anew. Automatic expansion/replay count is zero. Do not introduce
a retry of the original message after any mutating tool has run.

Routing keeps up to four completed chat-local user turns as bounded intent hints.
Parameter-only replies and unfamiliar wording can retain the relevant module;
the LLM interprets the current message using actual dialogue. A new explicit
domain ends the previous task. Selected project meshes alone do not transfer
numeric-reply intent into another chat. Availability is never authorization.

MAF tool(bound_method) reads function docstrings and Annotated parameters with
Pydantic Field descriptions, as its @tool decorator does. Use these descriptions
to distinguish new actions, inspection and approval; include actual supported
dimensions, families, units and missing-parameter behavior. Keep service methods
callable for backend callers. Composition budgets these schemas, and integration
tests inspect the actual schemas sent by MAF, including parameter descriptions.

The selections module currently supplies inspection guidance and explicit limits;
this repository has no agent face-picking or persistent named-selection methods.
No simulation module is registered. Implementing those capabilities is a separate
phase. The factory's original two-argument form and all-tools helper remain for
external callers; production chat always supplies an AgentComposition.

## Diagnostics and evaluation

Structured agent_composition and agent_completion log records include scoped IDs,
selected modules, reasons, available/invoked tool names, route misses, timings,
and token estimates. They omit prompts, filenames, tool arguments, and tool
results. Provider usage, when present, is reported separately; it may aggregate
multiple model rounds. Estimates retain the existing bytes/3 + framing heuristic
and use the existing context budget, summaries, and role-aware history.

Run the offline benchmark with the backend Python environment:

```powershell
.venv/Scripts/python.exe scripts/benchmarks/agent_architecture.py --samples 30
```

`--live` additionally exercises the configured local model with six isolated
workloads and real worker verification. It never accesses application projects.
The small live sample does not justify p95 latency or universal speedup claims.
See docs/PHASE_11_18B5_IMPLEMENTATION_REPORT.md for the measured release results.
