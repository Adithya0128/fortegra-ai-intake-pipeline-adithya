# Customer Complaint Triage

## Business Context

When a customer contacts Fortegra with a complaint — about a denied claim, a billing dispute, adjuster conduct, or coverage confusion — the complaint needs to be triaged quickly and accurately. The wrong routing decision can turn a resolvable situation into a regulatory complaint, a lawsuit, or a lost long-term customer.

Currently, complaints are routed manually. A team member reads the complaint, assesses its urgency and nature, determines whether it needs supervisor escalation, legal review, or regulatory flagging, and drafts or selects a response. This process is time-sensitive, emotionally demanding, and prone to inconsistency when volume spikes.

You are being asked to build an AI-powered pipeline that automates this triage process.

---

## What the System Needs to Do

Your pipeline must:

1. Ingest the incoming customer complaint from `data/complaints/complaint_sample.json`
2. Classify the complaint — type, urgency, and customer sentiment
3. Apply the routing and escalation rules from `data/complaints/routing_guidelines.json`
4. Determine the appropriate response path and any required escalations
5. Draft a response to the customer appropriate to the situation
6. Produce a formatted markdown triage report written to `output/`

---

## What the Report Must Contain

- Complaint classification — type, sentiment, urgency level
- Escalation determination — supervisor, legal review, regulatory flag — with reasoning
- Recommended response path and owner
- Draft customer response
- Risk assessment — what happens if this is mishandled
- Confidence level and any items requiring human judgment before action is taken

---

## Input Data

| File | Description |
|------|-------------|
| `data/complaints/complaint_sample.json` | The incoming customer complaint |
| `data/complaints/routing_guidelines.json` | Escalation triggers, urgency levels, and tone guidelines |
| `data/policies/policy_records.json` | Policy records if relevant to the complaint context |

---

## How to Run

```bash
python src/run.py --scenario complaint_triage
```

If you implement your own entry point, document it clearly in your PR description.

---

## Output

Your pipeline should write a formatted markdown report to:

```
output/CMP-2026-01193_triage.md
```

The report must be immediately usable by the team member who picks it up — they should be able to read it, understand the situation fully, and act on it without needing to re-read the original complaint.

---

## PR Submission Requirements

Your pull request must include:

- Your complete pipeline code
- The generated output file in `output/`
- An architectural diagram showing your pipeline flow — inputs, processing steps, decision points, and output. Any format is acceptable — Mermaid, draw.io, image, or any other tool you choose.
- A PR description summarizing what you built and how to run your pipeline if it differs from the default entry point.
