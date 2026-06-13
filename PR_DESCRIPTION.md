# Customer Complaint Triage Pipeline

## What this does

An AI pipeline that triages an incoming customer complaint end-to-end: it classifies
the complaint, looks up the policy on file, runs a deterministic identity check,
determines supervisor / legal / regulatory escalations, drafts a ready-to-send
customer response, assesses risk, independently validates the escalation decisions,
and writes a formatted markdown triage report a team member can act on without
re-reading the original complaint.

**Output:** `output/CMP-2026-01193_triage.md` (committed in this PR)

## How to run

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add your ANTHROPIC_API_KEY
python src/run.py --scenario complaint_triage
```

Runs from any working directory — all data/output paths are anchored to the repo root.

## Architecture

Prompt-chaining **workflow** (not an autonomous agent) with one tool-use step, a
deterministic spine, and an independent validation pass. Full diagram and rationale
in [`ARCHITECTURE.md`](./ARCHITECTURE.md); the end-to-end process narrative is in
[`WORKFLOW.md`](./WORKFLOW.md).

```
classify → fetch policy (tool) → identity check (code) → route/escalate
   → draft → assess risk → validate (LLM-as-judge) → assemble report (code)
```

- **Model:** `claude-opus-4-8` everywhere, with adaptive thinking on the judgment-heavy steps.
- **Structured outputs:** every LLM step returns a validated Pydantic object — no
  fragile text parsing, and `extra="forbid"` stops the model inventing fields or
  out-of-vocabulary categories.
- **Code, not LLM, for deterministic work:** response-deadline math (with an `OVERDUE`
  check) and the name-vs-holder identity comparison run in Python — the model is
  reserved for genuine judgment.
- **Independent validation:** a separate LLM invocation re-checks the escalation
  decisions against the same source evidence the router had, without having made them.

## Why chaining (not a single prompt)

On token cost alone, a single cached prompt could beat this design — that is *not*
why it's chained. Two things a single prompt structurally cannot do:

1. **Run deterministic code between reasoning steps** — the identity check is an exact
   comparison that cannot silently fail to fire; a single prompt could only be *asked*
   to check. On a triage where disclosing the wrong policyholder's details is a PII
   breach, that guarantee is the point.
2. **Independently verify itself** — stage 6 audits stage 3 in a separate invocation
   that never saw stage 3's reasoning, so it re-derives rather than rationalises.

## Production hardening

- SDK-native retry backoff (429/5xx), with a widened retry budget — not reimplemented.
- Raised `max_tokens` on the thinking stages so a long reasoning trace can't truncate
  the structured JSON mid-object.
- Fail-closed on both API and non-API errors (e.g. a Pydantic validation failure):
  aborts on the named stage rather than half-writing a compliance report.

## Files

| File | Role |
|---|---|
| `src/run.py` | CLI entry point |
| `src/pipeline.py` | Orchestration: the six stages + deterministic helpers + report assembly |
| `src/schemas.py` | Pydantic output schemas (typed contract for each LLM step) |
| `src/tools.py` | `lookup_policy` tool definition + dispatch |
| `ARCHITECTURE.md` | Pipeline diagram and design rationale |
| `DESIGN.md` | Design document (tech stack, models, patterns, assumptions, future work) |
| `WORKFLOW.md` | End-to-end process narrative — how a complaint becomes a report |
| `PROJECT_GUIDE.md` | File-by-file guide + future work + the caching approach |

## Edge cases handled

**Data & identity**
- **Identity mismatch** between the complainant and the policyholder on file →
  flagged deterministically and surfaced as a human-judgment gate before any coverage
  discussion. *(This is the planted trap in the sample data: POL-10031 is held by
  Diana Chu, not the complainant Brenda Alcott.)*
- **Missing policy record** → an explicit "no policy record found" discrepancy instead
  of a crash; the report degrades gracefully with `N/A` fields.
- **Out-of-vocabulary outputs blocked** — `Literal` enums + `extra="forbid"` mean the
  model cannot invent a category, sentiment, urgency level, or extra field outside the
  routing guidelines.
- **Missing/optional fields** in the report render as `N/A`, and empty attachments as
  `None`, rather than raising.

**Routing, escalation & timing**
- **Multiple escalations firing at once** (supervisor + legal + regulatory), each
  grounded in the exact triggering rule string — never an invented reason.
- **Semantic contradictions** in the free text (e.g. "never had a claim" vs.
  `prior_claims: 1`, or standing-to-file questions) that structured-field checks miss.
- **Overdue SLA deadline** — a deadline already in the past is marked `OVERDUE` rather
  than presented as freshly actionable.
- **Business-calendar SLA math in code** — Mon–Fri / 9–17, per-urgency SLA, so the
  response deadline is never a model hallucination.
- **Unparseable `received_date`** → an explicit "Unknown" deadline instead of a crash.

**Response drafting**
- **Tone gated by sentiment** — `furious` → acknowledge-first and non-defensive;
  `upset`/`frustrated` → empathise-then-explain; etc., driven by the guidelines.
- **Letter safety rails** — never promises to overturn the denial, confirms the exact
  attachments by name, addresses regulator/attorney threats calmly, and raises identity
  verification respectfully when a mismatch exists.

**Output integrity & robustness**
- **Independent validation surfaced in the header** — a ⚠ banner replaces the ✅ when
  the LLM-as-judge flags an issue, so a reviewer is warned before acting.
- **API failure after retries** → fail-closed with the failing stage named, no
  half-written compliance report (assembly is deterministic and outside the guard).
- **Truncation guard** — raised `max_tokens` on the thinking stages so a long reasoning
  trace can't cut off the structured JSON mid-object and fail validation.
- **Path-independence** — runs correctly from any working directory (all paths anchored
  to the repo root).

## Note

`PR_DESCRIPTION.md`, `DESIGN.md`, `WORKFLOW.md`, and `PROJECT_GUIDE.md` are included
for review convenience; the design document is also emailed to the contact per the
assignment instructions.
