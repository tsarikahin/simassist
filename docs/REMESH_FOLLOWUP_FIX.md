# Conversational mesh-change follow-up fix

2026-11-15. This fixes the reported annulus conversation and generalizes the
handling of mesh edits and parameter replies; it adds no later-phase features.

## Findings

The reported geometry and selected triangular mesh were valid. The original
mesh had sizes 0.05–0.1 mm and 1,247 nodes. The failure had several causes:

1. A reply containing only a numerical size range did not match a domain and
   exposed workspace tools only, even after an explicit meshing conversation.
2. The capability helper recognized the module `meshing`, but treated operation
   labels such as `remeshing` as unknown. Its response could reinforce a false
   capability claim. An unloaded module also does not prove a product limitation.
3. Some tool descriptions were incomplete or misleading: generate_mesh mentioned
   tetrahedral support but omitted its 1D/2D families and new-version behavior.
4. Live testing found output exhaustion: the local reasoning model sometimes
   used all 768 allowed output tokens for reasoning, leaving an empty final
   reply. This was observable in provider usage, not inferred from reply quality.
5. The inherited-size proposal wording could suggest preserving sizes while
   increasing resolution. Preserving nominal sizes is not a refinement.

## Changes

- Routing uses up to four completed chat-local user turns. A numeric range or
  parameter reply can continue a meshing task without repeating a domain name.
  Unrecognized wording can retain relevant meshing tools for the LLM to interpret
  using actual dialogue. A new explicit domain interrupts the previous task;
  another chat's mesh selection alone does not supply conversational intent.
- Instructions describe intent: requesting a mesh change, supplying parameters,
  and approving a persisted proposal are separate operations. They contain no
  special recipe or hardcoded size values for the reported utterance.
- Mesh generation includes first meshes, refinement, coarsening, family changes
  and new versions of existing geometry. Explicit bounds do not require a pending
  proposal. Missing bounds require clarification, not invented settings.
- Capability lookup normalizes common operation aliases and distinguishes loaded
  from supported-but-unloaded modules. Unknown labels no longer produce a blanket
  assertion that the underlying operation is unsupported. No automatic tool
  expansion, action replay, or extra LLM classifier was introduced.
- Tool docstrings now describe actual support. Annotated parameters with Pydantic
  Field descriptions explain IDs, dimensions, families, units, missing sizes and
  confirmation semantics. MAF tool(bound_method) reads this metadata just as its
  @tool decorator does; service methods remain directly callable. Tests inspect
  the actual schemas sent to the provider and preserve original argument types,
  defaults, required fields, and tool names.
- Empty pending-proposal results explain how to start a new mesh request.
  Inherited-size proposals explicitly distinguish unchanged baseline values from
  an actual resolution change.
- The default SIMASSIST_RESPONSE_RESERVE_TOKENS increases from 768 to 2048, with
  the same configurable override and consistent context-budget accounting. The
  default available input budget changes from 14,080 to 12,800 tokens within the
  existing 16,384-token window. History truncation/summaries still respect it.
- Sync and streaming chat return a visible fallback if the provider supplies no
  final text. It reports actual submitted job IDs, or that no jobs were submitted,
  and never automatically retries the request. The fallback is persisted/cached,
  so request replay cannot submit the same work again.

## Verification

- **267 backend tests passed in 30.88 s.**
- Ruff lint and formatting pass.
- Frontend TypeScript/Vite production build passes; the existing large-bundle
  warning remains.
- Git diff whitespace checks pass.
- **81/81 routing fixtures** match expected domains; none exclude a required
  tool. Fixtures include alternative wording, numerical replies, repeated size
  corrections, coarsening, approvals, different chats, unrelated requests and
  unsupported simulation requests. These are curated cases, not a universal
  language-understanding accuracy claim.
- An integration regression exercises the exact annulus creation → mesh-change
  request → numerical sizes through both chat endpoints, installed MAF tool
  binding, durable history, proposal handling and the real worker. It verifies
  the existing geometry is reused, old mesh selection is preserved, the new mesh
  is finer, and replay creates no duplicate.
- API tests cover empty provider replies both with and without submitted jobs,
  including persistence, streaming events, cleanup and replay exclusion.

The updated offline report is
[agent-1118b5-followup-routing.json](benchmarks/agent-1118b5-followup-routing.json).
Average instruction/schema estimate over the expanded corpus is 2,931 tokens
versus the frozen pre-phase baseline of 6,420. Richer descriptions have a cost;
this remains a reduction of about 54%. Corpus mix and machine activity differ
from the original phase report, so its latency averages should not be compared
as a controlled speedup measurement.

## Real local model results

[remesh-followup.json](benchmarks/remesh-followup.json) records actual streaming
MAF calls to local spark-x2.6-4b, temperature 0, and real Gmsh worker results.
Each case uses its own isolated project with a deterministically built, verified
2D annulus and initial triangular mesh at 0.05–0.1 mm. All conversational edits
use the LLM. Application projects and existing user jobs were not modified.

| Conversation case | Result after explicit bounds | Nodes |
|---|---|---:|
| Original refinement wording | One completed mesh, 0.025–0.05 mm | 1,247 → 4,622 |
| Triangles look chunky / better resolution | One completed mesh, 0.025–0.05 mm | 1,247 → 4,622 |
| Back off density / less detail | One completed mesh, 0.1–0.2 mm | 1,247 → 350 |
| Retry after historical false “remeshing unavailable” answer | One completed mesh, 0.025–0.05 mm | 1,247 → 4,622 |

**4/4 cases passed:** no premature jobs during clarification, exactly one new
mesh per explicit request, correct bounds, same geometry, all jobs completed.
The three initial edit replies were visible and asked for bounds. Two used a
stored proposal; the coarsening case inspected current state and asked for
explicit bounds without storing one. The subsequent numerical reply worked in
both paths.

The initial 768-token run is retained as
[remesh-followup-768-initial.json](benchmarks/remesh-followup-768-initial.json).
It had blank intermediate replies and failed to recover from the false historical
claim. Its original pass flags checked final job correctness; the improved
harness also requires a visible clarification reply. Those earlier flags are
not evidence of good intermediate conversation behavior.

The final live requests took roughly 5–34 seconds each, including model reasoning
and tool rounds. Four cases are not a reliability or latency guarantee. A larger
output reserve fixes the observed exhaustion but cannot guarantee that any model
always finishes; the empty-reply fallback remains necessary. Backend validation,
scope checks, no-replay rules and targeted clarification still matter.

## Reproduce and apply

```powershell
.venv/Scripts/python.exe scripts/benchmarks/remesh_followup.py
.venv/Scripts/python.exe scripts/benchmarks/agent_architecture.py --samples 30 --output docs/benchmarks/agent-1118b5-followup-routing.json
```

Restart the backend to load the updated code and instruction resources. If an
explicit SIMASSIST_RESPONSE_RESERVE_TOKENS=768 override is configured, remove it
to use the new default or set an appropriate larger reserve. No chat reset or
artifact migration is required; the false-claim recovery case retains the old
conversation text and still performs the supported operation.
