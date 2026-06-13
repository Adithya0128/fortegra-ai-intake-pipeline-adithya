# Workflow — How a Complaint Becomes a Triage Report

This document walks through the pipeline end-to-end: what happens, in what order,
what each step consumes and produces, and how the pieces combine into the final
report. For the *why* behind the design, see `ARCHITECTURE.md` and `DESIGN.md`.

---

## The one-line shape

```
classify → fetch policy (tool) → identity check (code) → route/escalate
   → draft → assess risk → validate (LLM-as-judge) → assemble report (code)
```

Six LLM stages, three deterministic code steps interleaved between them, one markdown
report out. The control flow is fixed — every complaint takes exactly this path —
which is what makes the result reproducible and auditable.

---

## Step 0 — Load inputs

`run_complaint_triage()` reads two files from `data/`:

- `complaints/complaint_sample.json` — the incoming complaint.
- `complaints/routing_guidelines.json` — the routing rules (escalation triggers,
  urgency levels, sentiment categories, tone guidelines).

It then builds the Anthropic client (`max_retries=4`, `timeout=120`) and enters the
fail-closed block that wraps all the API stages.

---

## Stage 1 — Classify  *(LLM, no thinking)*

**In:** complaint + guidelines.
**Out:** `Classification` — `complaint_type`, `sentiment`, `urgency_level`,
`urgency_reasoning`, `incident_summary`.

The model must choose only from the guidelines' vocabulary — the Pydantic `Literal`
enums make any other value structurally impossible. Thinking is off here: it's a
bounded labelling task that doesn't need it. The `incident_summary` is a 2–3 sentence
plain-English digest so a busy human can grasp the case without reading the raw
complaint.

## Stage 2 — Fetch policy  *(LLM + `lookup_policy` tool)*

**In:** complaint.
**Out:** the policy record (or `None`).

The model is asked to retrieve the policy via the `lookup_policy` tool. We execute the
tool ourselves and **capture the structured record directly from our own dispatch**,
so downstream code gets clean typed data regardless of how the model phrases its
confirmation. (Honest note: for a primary-key lookup this round-trip is illustrative;
a direct call would do the same job more cheaply.)

## Code step — Identity check  *(deterministic, no LLM)*

**In:** complaint + policy.
**Out:** a list of structured discrepancy strings.

`_field_discrepancies` does an exact, case-normalised comparison of the complaint's
`customer_name` against the policy's `holder_name`. If they differ, it emits a
**NAME MISMATCH** flag requiring identity verification before any coverage discussion.
This is the load-bearing reason the pipeline is chained rather than a single prompt:
this check *provably runs*, every time — it cannot be skipped under model load. If no
policy was found, it emits a "no policy record" flag instead.

*(On the sample data this fires: POL-10031 is held by Diana Chu, but the complaint is
from Brenda Alcott — the planted trap.)*

## Stage 3 — Route / escalate  *(LLM, adaptive thinking)*

**In:** complaint + classification + policy + the pre-computed discrepancies + guidelines.
**Out:** `EscalationResult` — the three escalation decisions (supervisor / legal /
regulatory), each with the **exact** triggering rule strings; plus
`semantic_discrepancies` (free-text contradictions like "never had a claim" vs.
`prior_claims: 1`), the `response_owner`, and the `recommended_response_path`.

The model is told to check every trigger in all three categories and to never invent a
reason. It's also told *not* to repeat the pre-computed structured discrepancies — code
owns those; the model adds only what code can't see.

## Code step — Compute deadline  *(deterministic, no LLM)*

**In:** `received_date` + the chosen `urgency_level`.
**Out:** an SLA deadline string.

`_compute_deadline` maps urgency → SLA (critical = 4 business hours, high = 24 business
hours, standard = 3 days, low = 5 days) and advances over a Mon–Fri / 9–17 business
calendar. Date math never goes to the model. If the computed deadline is already in the
past, it's marked **OVERDUE** so a stale complaint isn't presented as freshly
actionable.

## Stage 4 — Draft  *(LLM, adaptive thinking)*

**In:** complaint + classification + escalation decisions.
**Out:** a ready-to-send customer letter (plain text).

The sentiment selects the tone guideline (e.g. `furious` → acknowledge-first,
non-defensive). The letter is constrained to: open by acknowledging the specific
frustration; confirm the exact attachments by name; **not** promise to overturn the
denial; commit to the promised next step and timeframe; address regulator/attorney
threats calmly; and raise identity verification respectfully when a mismatch exists.

## Stage 5 — Assess risk  *(LLM, adaptive thinking)*

**In:** complaint + classification + escalation + all discrepancies (structured + semantic).
**Out:** `RiskAssessment` — `risk_level`, `risk_factors`, `mishandling_consequences`
(regulatory / legal / reputational), `confidence_level` (0–100), `confidence_reasoning`,
and `human_judgment_required`.

## Stage 6 — Validate  *(LLM-as-judge, adaptive thinking)*

**In:** complaint + policy + pre-computed discrepancies + the escalation decisions + guidelines.
**Out:** `ValidationResult` — `escalations_correct`, `issues_found`, `assessment`.

A separate model invocation that **did not make** the escalation decisions audits them
against the same source evidence the router had. Because it never saw the router's
reasoning, it re-derives rather than rationalises — it has surfaced real gaps on the
sample (e.g. a missed E&O escalation reason, and that the ">$10k denied claim" trigger
can't be confirmed because the claim amount isn't in the data).

---

## Final step — Assemble report  *(deterministic, no LLM)*

`_assemble_report` stitches everything into an 8-section markdown report and writes it
to `output/CMP-2026-01193_triage.md`:

1. Complaint overview + incident summary
2. Classification
3. Policy record & data discrepancies
4. Escalation determination (with the exact rule strings)
5. Recommended response path + owner
6. Draft customer response
7. Risk assessment
8. Confidence, validation result & human-judgment items

The header carries the urgency, risk level, response deadline (with `OVERDUE` if
applicable), and a banner showing whether independent validation passed. Report
assembly is pure code and sits **outside** the error-handled block, so it never
produces a half-written report.

---

## What happens when something goes wrong

- **API error after retries** — the SDK retries 429/5xx with backoff; if it still
  fails, the pipeline prints `✗ Aborted on an Anthropic API error: …` naming the stage
  (from the `[N/6]` line) and exits non-zero. No partial report is written.
- **Non-API error** (e.g. a Pydantic validation failure or unexpected model response)
- **Truncated reasoning** — the thinking stages run with raised `max_tokens` so a long
  trace can't cut off the structured JSON mid-object.
- **Missing policy / unparseable date** — handled explicitly (a discrepancy flag / an
  "Unknown" deadline) rather than crashing.

---

## Observed result on the sample complaint

`CMP-2026-01193` → **Urgency: CRITICAL · Risk: CRITICAL**, all three escalations fired
(supervisor + legal + regulatory), identity mismatch caught, validation **PASSED**.
The full output is committed at `output/CMP-2026-01193_triage.md`.
