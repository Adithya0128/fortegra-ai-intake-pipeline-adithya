# Design Document — Customer Complaint Triage Pipeline

## 1. Tech stack

- **Language:** Python 3
- **AI:** Anthropic Python SDK (`anthropic`), Messages API with tool use and
  structured outputs
- **Validation/typing:** Pydantic v2 — one schema per LLM step, giving a typed
  contract for every structured response
- **Config:** `python-dotenv` for the API key
- **Robustness:** SDK-native retries (widened budget, not reimplemented), raised
  token headroom on the thinking steps to prevent truncated structured output, and
  fail-closed error handling so a failed call never produces a half-written report.
- No external services, databases, or vector stores — everything runs from the
  repo data and the Anthropic API, per the constraints.

## 2. Models used

- **`claude-opus-4-8` for every step in this submission — a deliberate single-model
  choice.** The four judgment-heavy steps (routing/escalation, drafting, risk, and the
  independent validation) genuinely need Opus-tier reasoning: they touch legal,
  regulatory, and E&O-sensitive territory where a mistake is expensive. I ran
  classification on Opus as well, deliberately, to keep the submission to one model —
  a single behaviour to reason about, test, and defend, with no second model's quirks
  to account for.
- **Adaptive thinking** (`thinking: {type: "adaptive"}`) is enabled only on the four
  judgment-heavy steps so the model decides how much to reason per case. Classification
  runs without thinking — it is a simple, bounded task.
- **The honest tradeoff:** using Opus for classification is marginally wasteful on raw
  tokens. Choosing the complaint type, sentiment, and urgency from the guidelines'
  *closed lists* is a bounded task that doesn't need Opus-tier reasoning, and because
  the step uses structured outputs the schema is guaranteed identical regardless of
  model — so it is purely a cost question, not a quality one. At single-complaint,
  run-once volume the saving is negligible, so I traded it for single-model simplicity.
  **In production at volume I would tier classification down to a cheaper model such as
  Haiku 4.5** — a one-line, near-zero-risk change given the locked output schema. It is
  a conscious simplicity-vs-cost call at this scale, not an oversight.

## 3. Agentic pattern(s)

**Prompt-chaining workflow with one tool-use step and an independent validation pass.**

Following Anthropic's own framing, I distinguish *workflows* (LLMs orchestrated
through fixed, code-driven paths) from *agents* (the model directs its own process).
This triage has an identical, well-defined flow for every complaint, so a workflow is
the correct and more defensible choice — a dynamic orchestrator-agent would add cost
and non-determinism with no benefit, and would hurt the auditability that a
legal/regulatory process needs.

Within that workflow:

- **Tool use** — the model calls a `lookup_policy` tool to ground its reasoning in the
  actual policy record before assessing coverage and escalations.
- **Structured outputs** — each step returns a validated Pydantic object, so the
  pipeline never parses free text and the model cannot emit malformed or extra fields.
- **Deterministic spine** — the core reason to chain rather than use one prompt:
  code runs *between* the LLM stages. Response-deadline math (with an `OVERDUE`
  check) and the name-vs-holder identity comparison run in Python. The identity
  check is an exact comparison that cannot silently fail to fire — a single prompt
  could only be *asked* to check — and on a triage where disclosing the wrong
  policyholder's details is a reportable PII breach, that guarantee matters.
- **LLM-as-judge** — a final, independent reviewer re-checks the escalation decisions
  in a separate model invocation. It gets the same source evidence the router had
  (complaint, policy record, pre-computed discrepancies, guidelines) but did NOT make
  the decisions, so it audits the output rather than rationalising its own reasoning
  — the evaluator pattern.

**Patterns I considered and rejected:** a single all-in-one prompt (poor
auditability, one prompt juggling six concerns); and an orchestrator-worker agent
(over-engineering for a fixed flow).

## 4. Assumptions

- The complaint's `policy_number` is the correct key for policy lookup, even when the
  complainant's name doesn't match the holder on file — the mismatch is surfaced for
  human verification rather than treated as a different policy.
- "Business hours/days" for SLA deadlines mean a Monday–Friday, 09:00–17:00 calendar,
  with the complaint assumed received at 09:00 on its `received_date`. Holidays are not
  modeled.
- The routing guidelines are the single source of truth for escalation triggers,
  urgency levels, and response tone.
- A denied claim that is technically correct under the policy can still carry E&O and
  reputational risk if the customer alleges they were never informed — the pipeline
  treats that as a risk to flag, not a closed matter.
- One complaint per run; the output filename is derived from the complaint ID.

## 5. What I would do differently with more time

- **Evaluation harness** — a labeled set of complaints with expected escalations, so
  the pipeline's decisions can be measured (precision/recall on escalations) rather
  than judged by eye.
- **Human-in-the-loop gate** — for `critical` cases or when validation flags an issue,
  hold the draft for explicit sign-off before it can be sent.
- **Richer policy reasoning** — cross-reference coverage terms and prior claims more
  deeply, and cite the specific policy clause behind a denial in the report.
- **Batch + observability** — process complaint queues via the Batches API and log
  token usage, latency, and confidence per step for monitoring.
- **Stage-level checkpointing & resume** — persist each stage's validated output
  (keyed by complaint ID + stage) so a failure in a later stage — including a
  non-API error the SDK won't retry, such as a Pydantic validation failure — resumes
  from that stage instead of re-running the whole chain and re-paying for earlier
  calls. The key would hash the inputs and prompt/code version so a changed prompt or
  complaint can never resume on stale data (a wrong resume on a compliance report is
  worse than an honest re-run). Out of scope at single-complaint volume, valuable at
  production scale.
- **Single-prompt + prompt caching as the cheaper baseline** — the chained design
  re-sends the guidelines and complaint to several stages, so on pure token cost a
  single cached prompt would likely win. I traded that cost for the deterministic
  checkpoints and independent verification above. If cost became the constraint at
  volume, I'd restructure the stable context (guidelines + complaint) into a cached
  prefix — after confirming it clears Opus 4.8's 4,096-token cache floor, which it
  may not. The largest caching win is *cross-complaint* (the guidelines are identical
  for every complaint), and that benefit is available to either design — so caching
  is a cost argument, not an argument against chaining.
- **Simplify the policy lookup to a direct call** — the tool-use round-trip is
  illustrative; a keyed dictionary fetch doesn't need a model in the loop.
