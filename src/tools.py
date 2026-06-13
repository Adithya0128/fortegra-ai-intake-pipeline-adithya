"""
The `lookup_policy` tool.

Exposed to Claude as a function it can call during the enrichment step. We keep
policy lookup as a real tool (rather than a silent code fetch) to demonstrate the
agentic tool-use pattern: the model decides it needs grounding data and requests
it. Because we own the dispatch function, we also capture the structured policy
record directly — so the rest of the pipeline gets clean typed data regardless.
"""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_POLICY_RECORDS = _ROOT / "data" / "policies" / "policy_records.json"

TOOL_DEFINITIONS = [
    {
        "name": "lookup_policy",
        "description": (
            "Look up a Fortegra policy record by policy number. Returns the holder "
            "name on file, coverage type, policy status, deductible, coverage limit, "
            "covered vehicles, and prior-claims count. Call this to ground any "
            "coverage or escalation reasoning in the actual policy on file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_number": {
                    "type": "string",
                    "description": "The policy number to retrieve, e.g. POL-10031",
                }
            },
            "required": ["policy_number"],
        },
    }
]


def lookup_policy(policy_number: str) -> dict | None:
    """Return the policy record matching `policy_number`, or None if not found."""
    records = json.loads(_POLICY_RECORDS.read_text())
    for record in records:
        if record["policy_number"] == policy_number:
            return record
    return None


def dispatch(name: str, inputs: dict) -> str:
    """Execute a tool call by name and return a JSON string for the model."""
    if name == "lookup_policy":
        record = lookup_policy(inputs["policy_number"])
        if record is None:
            return json.dumps(
                {"error": f"Policy {inputs['policy_number']} not found in records"}
            )
        return json.dumps(record, indent=2)
    return json.dumps({"error": f"Unknown tool: {name}"})
