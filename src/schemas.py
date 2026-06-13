"""
Typed output schemas for each LLM step in the triage pipeline.

Every Claude call that produces structured data returns one of these models via
the Anthropic SDK's structured-output support (`client.messages.parse`). This
replaces fragile regex/JSON parsing with guaranteed, schema-valid output that we
can rely on downstream.

`extra="forbid"` maps to JSON Schema `additionalProperties: false`, which the
structured-output API requires — the model cannot invent extra keys.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

UrgencyLevel = Literal["critical", "high", "standard", "low"]
Sentiment = Literal[
    "furious", "very_upset", "upset", "frustrated", "disappointed", "neutral"
]
ComplaintType = Literal[
    "claim_denial_dispute",
    "claim_delay",
    "coverage_misunderstanding",
    "adjuster_conduct",
    "billing_dispute",
    "cancellation_dispute",
    "general_dissatisfaction",
]
ResponseOwner = Literal["adjuster", "supervisor", "legal_team", "compliance_team"]
RiskLevel = Literal["critical", "high", "medium", "low"]


class Classification(BaseModel):
    """Step 1 — what kind of complaint is this, and how urgent."""

    model_config = ConfigDict(extra="forbid")

    complaint_type: ComplaintType
    sentiment: Sentiment
    urgency_level: UrgencyLevel
    urgency_reasoning: str
    incident_summary: str  # 2-3 sentence plain-English summary for the human reader


class Escalations(BaseModel):
    """The three escalation decisions, each grounded in the exact rule strings."""

    model_config = ConfigDict(extra="forbid")

    supervisor_required: bool
    supervisor_reasons: list[str]
    legal_review_required: bool
    legal_review_reasons: list[str]
    regulatory_flag_required: bool
    regulatory_flag_reasons: list[str]


class EscalationResult(BaseModel):
    """Step 3 — routing and escalation determination."""

    model_config = ConfigDict(extra="forbid")

    escalations: Escalations
    semantic_discrepancies: list[str]  # contradictions the model finds in free text
    response_owner: ResponseOwner
    recommended_response_path: str


class RiskAssessment(BaseModel):
    """Step 5 — what happens if mishandled, plus confidence and human-judgment items."""

    model_config = ConfigDict(extra="forbid")

    risk_level: RiskLevel
    risk_factors: list[str]
    mishandling_consequences: str
    confidence_level: int  # 0-100
    confidence_reasoning: str
    human_judgment_required: list[str]


class ValidationResult(BaseModel):
    """Step 6 — independent LLM-as-judge check of the escalation decisions."""

    model_config = ConfigDict(extra="forbid")

    escalations_correct: bool
    issues_found: list[str]  # missed or incorrectly-fired escalations, if any
    assessment: str
