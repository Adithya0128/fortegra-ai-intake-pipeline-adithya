# Fortegra AI Intake Pipeline — Take-Home Assignment

Welcome to the Fortegra Round 3 take-home exercise. Read this document fully before you begin — your deadline and defense session date have been communicated to you separately.

---

## What This Is

You are building an AI pipeline for a realistic Fortegra business scenario. The scenario involves ingesting structured input data, orchestrating one or more AI-powered processing steps, and producing a formatted output report.

This is not a puzzle or a trick. It reflects the kind of work you would be doing on your first week at Fortegra.

---

## Your Scenario: Customer Complaint Triage

Read the scenario README before writing any code:

- `scenarios/complaint_triage/README.md`

---

## Repository Structure

```
fortegra-ai-intake-pipeline/
│
├── data/
│   ├── policies/
│   │   └── policy_records.json           ← Policy lookup data
│   └── complaints/
│       ├── complaint_sample.json         ← Scenario input
│       └── routing_guidelines.json       ← Routing and escalation rules
│
├── scenarios/
│   └── complaint_triage/README.md        ← Start here
│
├── src/
│   └── run.py                            ← Stubbed entry point (implement here or replace)
│
├── output/                               ← Your pipeline writes here
│
├── requirements.txt
├── .env.example
└── README.md                             ← You are here
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/FortegraCorp/fortegra-ai-intake-pipeline.git
cd fortegra-ai-intake-pipeline
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up your API key

```bash
cp .env.example .env
```

Open `.env` and replace `your_api_key_here` with the Anthropic API key provided to you separately. Do not commit your `.env` file.

### 5. Verify your setup

```bash
python -c "import anthropic; print('Anthropic SDK ready')"
```

---

## Running Your Pipeline

The stubbed entry point is `src/run.py`. You can implement your pipeline there or structure it however makes sense for your approach.

```bash
python src/run.py --scenario complaint_triage
```

If you restructure the entry point, document how to run your pipeline in your PR description.

---

## What to Submit

### 1. GitHub Pull Request

1. **Create a branch** named `candidate/<your-last-name>` from `main`
2. **Commit your work** — including your output file in the `output/` directory
3. **Open a Pull Request** to `main`

Do not merge your PR. We will review it before the defense session.

### 2. Design Document

Email your design document to Lisa Martin at **lmartin@fortegra.com** before your deadline. Your design document must cover:

- **Tech stack** — languages, frameworks, and libraries used
- **Models used** — which Anthropic models you selected and why
- **Agentic pattern(s)** — the pattern(s) you chose and your reasoning behind them
- **Assumptions** — any assumptions you made about the business problem
- **What you would do differently** — given more time, what would you change or improve

---

## Expectations and Constraints

**Use AI tools freely.** Claude, ChatGPT, Copilot — use whatever you normally use. This is expected and encouraged. The work we are evaluating is your judgment: the patterns you chose, the edge cases you handled, and the decisions you can defend.

**Use the Anthropic API directly.** Everything you need is available through the Anthropic Python SDK.

**No external services required.** Everything you need is in this repository and the Anthropic API. Do not build a database, stand up a vector store, or call any external APIs.

**The output file matters.** Your markdown report will be read by a Fortegra team member during the defense. It should be human-readable, well-structured, and genuinely useful to someone handling a customer complaint.

**The defense matters more than the submission.** During the defense session you will walk through your code, explain every architectural decision, and demonstrate your pipeline running live. Be prepared to discuss what you chose, what you rejected, and where your implementation is weakest.

---

## API Key Notes

The Anthropic API key provided to you has a spend limit and will be revoked after the defense session. Please use it responsibly — it is intended for development and testing of this exercise only.

---

## Questions

If you have a genuine setup question, reach out to the Fortegra HR contact. We will not answer questions about which approach to take or which patterns to use — those decisions are yours to make and defend.

Good luck.
