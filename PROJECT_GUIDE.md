# Project Guide — File-by-File + Future Work

A map of every file in this repository, what it does, and why it exists — followed
by what I would build next given more time, including a concrete plan for prompt
caching.

---

## 1. What each file does

### Source (`src/`)

| File | Responsibility |
|---|---|
| `run.py` | **CLI entry point.** Parses `--scenario`, validates that the scenario exists, and dispatches `complaint_triage` to the pipeline. Anchors its scenario path to the repo root so it runs from any working directory. Other scenarios are stubbed (the take-home implements one). |
| `pipeline.py` | **The orchestrator.** Owns the fixed six-stage control flow, the deterministic helpers that run *between* stages, the error-handling boundary, and the markdown report assembly. This is where the architecture lives. |
| `schemas.py` | **Typed output contracts.** One Pydantic model per LLM step (`Classification`, `EscalationResult`, `RiskAssessment`, `ValidationResult`, plus the nested `Escalations`). `Literal` enums constrain the model to the guidelines' vocabulary; `extra="forbid"` forbids invented fields. Every structured call validates against one of these. |
| `tools.py` | **The `lookup_policy` tool.** The tool definition exposed to Claude plus the `dispatch`/`lookup_policy` functions that read `policy_records.json`. Path-anchored to the repo root. |

### `pipeline.py` internal structure

- **Client + parse helpers** — `_client()` (configures retries/timeout), `_parse()` (one structured Claude call → validated Pydantic object), `_run_policy_tool()` (the agentic tool loop).
- **Deterministic helpers (no LLM)** — `_add_business_days/hours`, `_compute_deadline` (SLA + `OVERDUE` detection), `_field_discrepancies` (name-vs-holder identity check).
- **LLM stages** — `_classify`, `_route`, `_draft`, `_assess_risk`, `_validate`.
- **Report assembly (no LLM)** — `_assemble_report` builds the markdown.
- **Orchestration** — `run_complaint_triage()` wires it all together with the fail-closed boundary.

### Documentation

| File | Purpose |
|---|---|
| `README.md` | The assignment brief + setup/run instructions. |
| `ARCHITECTURE.md` | The Mermaid pipeline diagram, stage-by-stage table, the "why this shape" rationale, and runtime-robustness notes. |
| `DESIGN.md` | The required design document: tech stack, models used, agentic patterns, assumptions, and future work. Emailed to the contact per the brief. |
| `WORKFLOW.md` | A prose walkthrough of how one complaint becomes one report — the data flowing through each stage. |
| `PROJECT_GUIDE.md` | This file. |
| `PR_DESCRIPTION.md` | The pull-request summary. |

### Data & config

| Path | Purpose |
|---|---|
| `data/complaints/complaint_sample.json` | The scenario input — the incoming complaint. |
| `data/complaints/routing_guidelines.json` | Escalation triggers, urgency levels, sentiment categories, tone guidelines — the single source of truth for routing. |
| `data/policies/policy_records.json` | Policy lookup data (the `lookup_policy` tool reads this). |
| `scenarios/complaint_triage/README.md` | The scenario specification. |
| `output/CMP-2026-01193_triage.md` | The generated triage report (committed). |
| `requirements.txt` | `anthropic`, `python-dotenv`, `pydantic`. |
| `.env.example` / `.gitignore` | API-key template; `.env` and caches are ignored, output is **not** ignored (it's a deliverable). |

---

## 2. What I would do with more time

- **Evaluation harness** — a labelled set of complaints with expected escalations, so
  the pipeline's decisions can be *measured* (precision/recall on escalations) rather
  than judged by eye.
- **Human-in-the-loop gate** — for `critical` cases or when validation flags an issue,
  hold the draft for explicit sign-off before it can be sent.
- **Richer policy reasoning** — cross-reference coverage terms and prior claims, and
  cite the specific policy clause behind a denial in the report.
- **Batch + observability** — process complaint queues via the Batches API; log token
  usage, latency, and confidence per step.
- **Stage-level checkpointing & resume** — persist each stage's validated output (keyed
  by complaint ID + stage) so a failure in a later stage — including a non-API error
  the SDK won't retry, like a Pydantic validation failure — resumes from that stage
  rather than re-running the whole chain. The cache key would hash the inputs and
  prompt/code version so a changed prompt or complaint never resumes on stale data (a
  wrong resume on a compliance report is worse than an honest re-run). Out of scope at
  single-complaint volume; valuable at production scale.
- **Simplify the policy lookup** — replace the illustrative tool-use round-trip with a
  direct keyed dictionary fetch (no model needed for a primary-key lookup).

---

## 3. Future work in depth: prompt caching

The interviewer's point is correct and worth stating plainly: **on token cost, a
single cached prompt could beat this chained design.** The guidelines hit four of the
six stages and the complaint hits all six, so we re-transmit shared context. A single
prompt would send it once. Caching is therefore a real future optimisation — but one
that needs to be done deliberately, not bolted on.

### Why the current structure wouldn't cache as-is

Caching is a **prefix match**: the API concatenates `tools → system → messages` into
one string and a cache hit requires the bytes to be **identical from position 0** up
to a `cache_control` breakpoint. In our pipeline every stage has a **different system
prompt** (classifier ≠ router ≠ validator), and the system block renders *before* the
user message that carries the guidelines. So the byte streams diverge at the very
start of each call — the identical guidelines sit *behind* a varying prefix and would
never produce a hit, even if we added a breakpoint.

### The restructure that makes it work

Move the stable bytes to the **front**, ahead of anything that varies, with the
breakpoint right after them:

```python
system = [
    {   # BLOCK 1 — identical bytes on every stage
        "type": "text",
        "text": f"ROUTING GUIDELINES:\n{guidelines}\n\nCOMPLAINT:\n{complaint}",
        "cache_control": {"type": "ephemeral"},      # breakpoint
    },
    {   # BLOCK 2 — per-stage instruction (varies freely, uncached)
        "type": "text",
        "text": "You are a Fortegra triage specialist determining escalations…",
    },
]
```

The cache has three independent tiers (tools / system / messages); a change to a
*later* system block doesn't invalidate an *earlier* cached one. So Block 1 caches on
stage 1 (≈1.25× write) and is read by stages 2–6 (≈0.1× each). The 5-minute TTL is a
non-issue — all six calls fire within seconds.

### The caveat that decides whether it's even worth it

On **Opus 4.8 the minimum cacheable prefix is 4,096 tokens.** Below that, the block
silently won't cache (`cache_creation_input_tokens: 0`, no error). Our guidelines +
complaint may be *under* that floor, in which case caching is a no-op here regardless
of structure. The honest plan is therefore:

1. `count_tokens` the stable block first.
2. If it clears 4,096 tokens, apply the stable-block-first restructure above.
3. Recognise the **largest** caching win is *cross-complaint* — the guidelines are
   identical for every complaint ever processed — and that benefit is available to a
   single-prompt design and a chained design equally.

Which is the key takeaway: **caching is a cost argument, not an argument against
chaining.** The reasons to chain — deterministic checkpoints between stages and an
independent verifier — are orthogonal to it.
