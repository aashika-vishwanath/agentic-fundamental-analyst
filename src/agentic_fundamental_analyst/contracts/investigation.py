"""Contracts for the Investigator (Phase 3) — the system's one agentic loop.

Two output types, same split pattern as every prior agent: InvestigatorAgentOutput
is what the model actually returns (EvidenceCandidate.url is unverified — the
model's word only); InvestigationVerdict is what run_investigator() returns after
deterministic URL-provenance grounding (agents/provenance.py) against the real
tool-return content in the run's own message history. See
.agents/plans/phase-3-investigator.md's Problem/Solution for the full rationale,
including why this deviates from PRD §6's `evidence: list[str]` sketch.
"""

from enum import Enum

from pydantic import BaseModel, Field

from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.financials import CoverageGap


class VerdictType(str, Enum):
    BENIGN = "benign"
    CONCERNING = "concerning"
    UNRESOLVED = "unresolved"


class EvidenceStance(str, Enum):
    SUPPORTS_BENIGN = "supports_benign"
    SUPPORTS_CONCERNING = "supports_concerning"
    CONTEXT = "context"


class SiblingFlagSummary(BaseModel):
    """Code-built, read-only context about a flag other than the one under
    investigation — metric/period/description only, never a full Flag or its
    source, and never another flag's verdict. Lets the Investigator note a
    suspected shared root cause without an extra tool call or agent run."""

    metric: str
    fiscal_year: int
    fiscal_period: str
    description: str


class EvidenceCandidate(BaseModel):
    """Agent-authored — url is NOT trusted until agents/provenance.py verifies
    it against the real tool-return content in the run's message history."""

    url: str
    claim: str
    stance: EvidenceStance


class InvestigatorAgentOutput(BaseModel):
    """The agent's own output_type. correlated_sibling_indices are 0-based
    positions into the sibling list the agent was given — never restated
    content, same closed-set-by-index idiom as the Flag Consolidator."""

    hypothesis: str
    verdict: VerdictType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[EvidenceCandidate]
    correlated_sibling_indices: list[int]


class EvidenceItem(BaseModel):
    """Post-grounding: url is verified to be a real URL the provider returned
    during this run."""

    url: str
    claim: str
    stance: EvidenceStance


class InvestigationTrajectory(BaseModel):
    """Code-derived from the run's message history (agents/provenance.py) —
    the substrate for trajectory evals, since native tool calls emit no
    OTel tool-call spans (see the plan's Research Findings §2)."""

    search_queries: list[str]
    result_urls: list[str]
    fetched_urls: list[str]
    distinct_domains: list[str]


class InvestigationVerdict(BaseModel):
    flag: ConsolidatedFlag
    verdict: VerdictType
    hypothesis: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem]
    correlated_sibling_indices: list[int]
    trajectory: InvestigationTrajectory
    dropped_evidence: list[str]
    coverage_gaps: list[CoverageGap]
