"""
Customer Complaint Triage — pipeline orchestration.

A prompt-chaining workflow (not an autonomous agent): the control flow is fixed
and code-driven, which is the right pattern for a high-stakes, auditable triage
where every decision must be reproducible. Each stage has one focused job.

Model: claude-opus-4-8 everywhere, with adaptive thinking on the judgment-heavy
steps. Deterministic work (policy lookup dispatch, deadline math, structured-field
discrepancy checks, report assembly) is kept in code, not the model.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import tools
from schemas import (
    Classification,
    EscalationResult,
    RiskAssessment,
    ValidationResult,
)

# Anchor data/output paths to the repo root so the pipeline runs from any
# working directory, not only the project root.
_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_OUTPUT = _ROOT / "output"

load_dotenv(_ROOT / ".env")

MODEL = "claude-opus-4-8"

# Business-hour SLA per urgency level, from routing_guidelines.json.
# (kind, amount): "high"=24 business hours, the rest as stated in the guidelines.
_SLA = {
    "critical": ("hours", 4),
    "high": ("hours", 24),
    "standard": ("days", 3),
    "low": ("days", 5),
}


# --------------------------------------------------------------------------- #
# Anthropic client helpers
# --------------------------------------------------------------------------- #
def _client() -> anthropic.Anthropic:
    # The SDK already retries 429 / 5xx with exponential backoff — we don't
    # reimplement that. We just widen the retry budget and set a per-call
    # timeout, which is appropriate for a long, multi-stage pipeline.
    return anthropic.Anthropic(max_retries=4, timeout=120.0)


def _parse(
    client: anthropic.Anthropic,
    system: str,
    user: str,
    schema: type,
    *,
    think: bool = False,
    max_tokens: int = 4096,
):
    """Structured Claude call → validated Pydantic instance of `schema`.

    `think=True` turns on adaptive thinking for the judgment-heavy steps; simple
    steps (classification) run without it to stay fast and cheap.
    """
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    if think:
        kwargs["thinking"] = {"type": "adaptive"}
        # Thinking tokens count toward max_tokens. Give the judgment-heavy steps
        # headroom so a long reasoning trace can't truncate the structured JSON
        # mid-object (which would fail validation).
        kwargs["max_tokens"] = max(max_tokens, 8000)
    return client.messages.parse(**kwargs).parsed_output


def _run_policy_tool(
    client: anthropic.Anthropic, complaint: dict
) -> dict | None:
    """Agentic tool step: let the model fetch the policy record via lookup_policy.

    Returns the policy record, or None if no matching policy exists. We capture
    the record from our own dispatch so downstream code gets clean structured
    data regardless of how the model phrases its confirmation.
    """
    captured: dict = {}
    messages = [
        {
            "role": "user",
            "content": (
                "Retrieve the policy record for this complaint so it can be triaged. "
                f"Complaint:\n{json.dumps(complaint, indent=2)}"
            ),
        }
    ]
    system = (
        "You are a Fortegra triage assistant. Use the lookup_policy tool to fetch "
        "the policy record for the complaint's policy_number. Once you have it, "
        "briefly confirm what you retrieved."
    )

    # Bounded loop: a single read-only lookup tool needs one round-trip; the cap
    # guards against a misbehaving model looping indefinitely on tool calls.
    for _ in range(5):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=tools.TOOL_DEFINITIONS,
        )
        if response.stop_reason != "tool_use":
            break

        results = []
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "lookup_policy":
                    rec = tools.lookup_policy(block.input["policy_number"])
                    if rec:
                        captured.update(rec)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tools.dispatch(block.name, block.input),
                    }
                )
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})

    return captured or None


# --------------------------------------------------------------------------- #
# Deterministic helpers (no LLM)
# --------------------------------------------------------------------------- #
def _add_business_days(start: datetime, n: int) -> datetime:
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            n -= 1
    return d


def _add_business_hours(start: datetime, n: int) -> datetime:
    """Advance over a 9:00-17:00, Mon-Fri business calendar."""
    d = start
    while n > 0:
        d += timedelta(hours=1)
        if d.weekday() < 5 and 9 <= d.hour <= 17:
            n -= 1
    return d


def _compute_deadline(received_date: str, urgency: str) -> str:
    """Compute the response deadline in code — never trust an LLM with date math.

    Assumes the complaint was received at 09:00 local on `received_date`, and a
    Mon-Fri / 9-17 business calendar.
    """
    try:
        start = datetime.strptime(received_date, "%Y-%m-%d").replace(hour=9)
    except ValueError:
        return "Unknown (could not parse received_date)"

    kind, amount = _SLA.get(urgency, ("days", 3))
    deadline = (
        _add_business_hours(start, amount)
        if kind == "hours"
        else _add_business_days(start, amount)
    )
    sla_text = f"{amount} business {kind}"
    overdue = "  ⚠ **OVERDUE**" if deadline < datetime.now() else ""
    return (
        f"{deadline:%Y-%m-%d %H:%M} ({sla_text} from receipt on {received_date})"
        f"{overdue}"
    )


def _field_discrepancies(complaint: dict, policy: dict | None) -> list[str]:
    """Deterministic structured-field cross-checks between complaint and policy."""
    if not policy:
        return [f"No policy record found for {complaint.get('policy_number')!r}."]

    found: list[str] = []

    c_name = complaint.get("customer_name", "").strip().lower()
    p_name = policy.get("holder_name", "").strip().lower()
    if c_name and p_name and c_name != p_name:
        found.append(
            f"NAME MISMATCH: complaint is from '{complaint['customer_name']}' but "
            f"policy {policy['policy_number']} is held by '{policy['holder_name']}' "
            "— identity verification required before any coverage discussion."
        )

    # NOTE: we deliberately do NOT flag a "tenure discrepancy" from the policy's
    # effective_date. A long-tenured customer on an annually-renewed policy has a
    # recent effective_date by design, so that comparison produces false positives.
    # True relationship history isn't in this dataset; the claimed-vs-actual claims
    # contradiction (a real signal) is left to the LLM's semantic check in _route.

    return found


# --------------------------------------------------------------------------- #
# LLM stages
# --------------------------------------------------------------------------- #
def _classify(
    client: anthropic.Anthropic, complaint: dict, guidelines: dict
) -> Classification:
    print("  [1/6] Classifying complaint...")
    system = (
        "You are a Fortegra complaint triage specialist. Classify the complaint "
        "using ONLY the categories, sentiments, and urgency levels defined in the "
        "routing guidelines. For incident_summary, write 2-3 plain-English sentences "
        "a busy team member can read to understand what happened and what the "
        "customer wants."
    )
    user = (
        f"COMPLAINT:\n{json.dumps(complaint, indent=2)}\n\n"
        f"ROUTING GUIDELINES:\n{json.dumps(guidelines, indent=2)}"
    )
    return _parse(client, system, user, Classification)


def _route(
    client: anthropic.Anthropic,
    complaint: dict,
    guidelines: dict,
    classification: Classification,
    policy: dict | None,
    field_flags: list[str],
) -> EscalationResult:
    print("  [3/6] Determining escalations and routing...")
    system = (
        "You are a Fortegra triage specialist determining escalations. Check the "
        "complaint against EVERY trigger in all three escalation categories in the "
        "routing guidelines. For each category you mark required, list the EXACT "
        "trigger strings from the guidelines that fired — never invent a reason. "
        "In semantic_discrepancies, note contradictions you find in the complaint's "
        "free text versus the policy record (e.g. claims history) that the "
        "structured-field checks would miss. Do not repeat the pre-computed "
        "structured discrepancies you are given."
    )
    user = (
        f"COMPLAINT:\n{json.dumps(complaint, indent=2)}\n\n"
        f"CLASSIFICATION:\n{classification.model_dump_json(indent=2)}\n\n"
        f"POLICY RECORD ON FILE:\n{json.dumps(policy, indent=2)}\n\n"
        f"PRE-COMPUTED STRUCTURED DISCREPANCIES:\n{json.dumps(field_flags, indent=2)}\n\n"
        f"ROUTING GUIDELINES:\n{json.dumps(guidelines, indent=2)}"
    )
    return _parse(client, system, user, EscalationResult, think=True)


def _draft(
    client: anthropic.Anthropic,
    complaint: dict,
    guidelines: dict,
    classification: Classification,
    escalation: EscalationResult,
) -> str:
    print("  [4/6] Drafting customer response...")
    sentiment = classification.sentiment
    if sentiment in ("furious", "very_upset"):
        tone_key = "furious_or_very_upset"
    elif sentiment in ("upset", "frustrated"):
        tone_key = "upset_or_frustrated"
    else:
        tone_key = "disappointed_or_neutral"
    tone = guidelines["routing_guidelines"]["response_tone_guidelines"][tone_key]

    system = (
        "You are a senior Fortegra customer relations specialist writing a "
        f"ready-to-send response to a customer complaint.\nTONE GUIDANCE: {tone}\n"
        "The letter must: open by acknowledging their specific frustration (not "
        "boilerplate); confirm receipt of their complaint and the exact attachments "
        "they sent; NOT promise to overturn the claim decision; commit to the "
        "specific next step and timeframe they were promised; address any threat to "
        "involve a regulator or attorney calmly and without defensiveness; and, if a "
        "data discrepancy requires identity verification, mention that step "
        "respectfully. Use the customer's actual name. Output only the letter."
    )
    user = (
        f"COMPLAINT:\n{json.dumps(complaint, indent=2)}\n\n"
        f"CLASSIFICATION:\n{classification.model_dump_json(indent=2)}\n\n"
        f"ESCALATION DECISIONS:\n{escalation.model_dump_json(indent=2)}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,  # headroom: adaptive thinking + a full-length letter
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _assess_risk(
    client: anthropic.Anthropic,
    complaint: dict,
    classification: Classification,
    escalation: EscalationResult,
    discrepancies: list[str],
) -> RiskAssessment:
    print("  [5/6] Assessing risk, confidence, and human-judgment items...")
    system = (
        "You are a Fortegra risk and compliance specialist. Assess this triage. "
        "risk_factors must be specific and reference the actual facts. "
        "mishandling_consequences must concretely cover regulatory, legal, and "
        "reputational outcomes. confidence_level is 0-100. human_judgment_required "
        "lists the specific items a human MUST review before any action is taken."
    )
    user = (
        f"COMPLAINT:\n{json.dumps(complaint, indent=2)}\n\n"
        f"CLASSIFICATION:\n{classification.model_dump_json(indent=2)}\n\n"
        f"ESCALATION ANALYSIS:\n{escalation.model_dump_json(indent=2)}\n\n"
        f"ALL DATA DISCREPANCIES:\n{json.dumps(discrepancies, indent=2)}"
    )
    return _parse(client, system, user, RiskAssessment, think=True)


def _validate(
    client: anthropic.Anthropic,
    complaint: dict,
    guidelines: dict,
    escalation: EscalationResult,
    policy: dict | None,
    field_flags: list[str],
) -> ValidationResult:
    print("  [6/6] Validating escalation decisions (LLM-as-judge)...")
    system = (
        "You are an independent Fortegra compliance reviewer. You did NOT make the "
        "escalation decisions below — your job is to audit them against the raw "
        "routing rules. You have the SAME source evidence the router had: the "
        "complaint, the policy record on file, the pre-computed structured "
        "discrepancies, and the routing guidelines — so verify the decisions "
        "against that evidence rather than assuming any referenced fact is "
        "unsupported. Check whether any required escalation was missed or any was "
        "fired without a matching trigger. Set escalations_correct accordingly and "
        "list any issues. Be strict: a missed legal or regulatory escalation is a "
        "serious error."
    )
    user = (
        f"COMPLAINT:\n{json.dumps(complaint, indent=2)}\n\n"
        f"POLICY RECORD ON FILE:\n{json.dumps(policy, indent=2)}\n\n"
        f"PRE-COMPUTED STRUCTURED DISCREPANCIES:\n{json.dumps(field_flags, indent=2)}\n\n"
        f"ESCALATION DECISIONS UNDER REVIEW:\n{escalation.model_dump_json(indent=2)}\n\n"
        f"ROUTING GUIDELINES:\n{json.dumps(guidelines, indent=2)}"
    )
    return _parse(client, system, user, ValidationResult, think=True)


# --------------------------------------------------------------------------- #
# Report assembly (no LLM)
# --------------------------------------------------------------------------- #
def _assemble_report(
    complaint: dict,
    classification: Classification,
    policy: dict | None,
    escalation: EscalationResult,
    discrepancies: list[str],
    deadline: str,
    draft: str,
    risk: RiskAssessment,
    validation: ValidationResult,
) -> str:
    esc = escalation.escalations
    p = policy or {}

    def yn(v: bool) -> str:
        return "**YES**" if v else "No"

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {x}" for x in items) if items else "- None"

    disc_block = (
        "\n".join(f"> ⚠ {d}\n" for d in discrepancies)
        if discrepancies
        else "None detected."
    )
    val_banner = (
        "✅ Escalation decisions validated by independent review."
        if validation.escalations_correct
        else "⚠️ **Validation flagged issues — see Section 8 before acting.**"
    )

    return f"""# Triage Report — {complaint['complaint_id']}

> **Generated:** {datetime.now():%Y-%m-%d %H:%M:%S}
> **Urgency:** {classification.urgency_level.upper()} · **Risk:** {risk.risk_level.upper()}
> **Response Deadline:** {deadline}
> {val_banner}

---

## 1. Complaint Overview

| Field | Value |
|-------|-------|
| Complaint ID | `{complaint['complaint_id']}` |
| Customer | {complaint['customer_name']} |
| Policy Number | `{complaint['policy_number']}` |
| Claim Reference | `{complaint['claim_reference']}` |
| Received | {complaint['received_date']} via {complaint['received_channel']} |
| Assigned Adjuster | {complaint['assigned_adjuster']} |
| Claim Status | **{complaint['current_claim_status'].upper()}** |
| Customer Tenure | {complaint['customer_tenure_years']} years |
| Prior Complaints | {complaint['prior_complaints']} |
| Attachments | {', '.join(complaint.get('attachments_included', [])) or 'None'} |

**Denial Reason on File:** {complaint.get('denial_reason_on_file', 'N/A')}

### Incident Summary

{classification.incident_summary}

---

## 2. Classification

| Dimension | Value |
|-----------|-------|
| Complaint Type | `{classification.complaint_type}` |
| Sentiment | `{classification.sentiment}` |
| Urgency | **{classification.urgency_level.upper()}** |

**Urgency Reasoning:** {classification.urgency_reasoning}

---

## 3. Policy Record & Data Discrepancies

| Field | Value |
|-------|-------|
| Holder Name on File | {p.get('holder_name', 'N/A')} |
| Coverage Type | `{p.get('coverage_type', 'N/A')}` |
| Status | {str(p.get('status', 'N/A')).upper()} |
| Premium Current | {'Yes' if p.get('premium_current') else 'No'} |
| Effective → Expiration | {p.get('effective_date', 'N/A')} → {p.get('expiration_date', 'N/A')} |
| Coverage Limit | ${p.get('coverage_limit', 0):,} |
| Deductible | ${p.get('deductible', 0):,} |
| Prior Claims on Record | {p.get('prior_claims', 'N/A')} |

### Discrepancies Requiring Attention

{disc_block}

---

## 4. Escalation Determination

### Supervisor Escalation: {yn(esc.supervisor_required)}
{bullets(esc.supervisor_reasons)}

### Legal Review: {yn(esc.legal_review_required)}
{bullets(esc.legal_review_reasons)}

### Regulatory Flag: {yn(esc.regulatory_flag_required)}
{bullets(esc.regulatory_flag_reasons)}

---

## 5. Recommended Response Path

**Owner:** `{escalation.response_owner}`

{escalation.recommended_response_path}

---

## 6. Draft Customer Response

```
{draft}
```

---

## 7. Risk Assessment

**Risk Factors:**

{bullets(risk.risk_factors)}

**If Mishandled:**

{risk.mishandling_consequences}

---

## 8. Confidence, Validation & Human Judgment

**Confidence Level:** {risk.confidence_level}%
**Reasoning:** {risk.confidence_reasoning}

**Independent Escalation Review:** {'PASSED' if validation.escalations_correct else 'ISSUES FOUND'}
{validation.assessment}

{bullets(validation.issues_found) if validation.issues_found else ''}

**Items Requiring Human Judgment Before Action:**

{bullets(risk.human_judgment_required)}

---

*Generated by the Fortegra AI Intake Pipeline · Model: {MODEL} · Pattern: prompt-chaining workflow with tool use and independent validation*
"""


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def yn_plain(v: bool) -> str:
    """Plain Yes/No for console output (the report uses its own markdown helper)."""
    return "Yes" if v else "No"


def run_complaint_triage() -> None:
    complaint = json.loads((_DATA / "complaints" / "complaint_sample.json").read_text())
    guidelines = json.loads(
        (_DATA / "complaints" / "routing_guidelines.json").read_text()
    )

    client = _client()
    cid = complaint["complaint_id"]
    print(f"\nProcessing {cid}...")

    try:
        classification = _classify(client, complaint, guidelines)

        print("  [2/6] Fetching policy record (tool use)...")
        policy = _run_policy_tool(client, complaint)
        field_flags = _field_discrepancies(complaint, policy)

        escalation = _route(
            client, complaint, guidelines, classification, policy, field_flags
        )
        all_discrepancies = field_flags + escalation.semantic_discrepancies

        draft = _draft(client, complaint, guidelines, classification, escalation)
        risk = _assess_risk(
            client, complaint, classification, escalation, all_discrepancies
        )
        validation = _validate(
            client, complaint, guidelines, escalation, policy, field_flags
        )
    except anthropic.APIError as e:
        # API failure the SDK couldn't recover from (retries already exhausted).
        # The [N/6] line printed last above points to the stage that failed.
        print(f"\n  ✗ Aborted on an Anthropic API error: {type(e).__name__}: {e}")
        raise SystemExit(1)
    except Exception as e:
        # Non-API failure the SDK won't retry — e.g. a Pydantic validation error
        # or an unexpected model response. Fail closed on the named stage rather
        # than half-writing a compliance report.
        print(f"\n  ✗ Aborted on an unexpected error: {type(e).__name__}: {e}")
        raise SystemExit(1)

    deadline = _compute_deadline(
        complaint["received_date"], classification.urgency_level
    )
    report = _assemble_report(
        complaint, classification, policy, escalation, all_discrepancies,
        deadline, draft, risk, validation,
    )

    _OUTPUT.mkdir(exist_ok=True)
    out = _OUTPUT / f"{cid}_triage.md"
    out.write_text(report)

    print(f"\n  Report written to: {out}")
    print(f"  Urgency: {classification.urgency_level.upper()} | Risk: {risk.risk_level.upper()}")
    print(
        f"  Escalations — Supervisor: {yn_plain(escalation.escalations.supervisor_required)} | "
        f"Legal: {yn_plain(escalation.escalations.legal_review_required)} | "
        f"Regulatory: {yn_plain(escalation.escalations.regulatory_flag_required)}"
    )
    print(
        f"  Validation: {'PASSED' if validation.escalations_correct else 'ISSUES FOUND'}"
    )
