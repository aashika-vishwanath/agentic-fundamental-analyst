from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.flags import Flag


class ConsolidatedFlag(BaseModel):
    flags: list[Flag]  # code-populated only — never constructed from raw agent output
    summary: str


class FlagGroupCandidate(BaseModel):
    # 0-based positions into the input list[Flag] (post-exact-dedup), as
    # given to the agent — never the flag's own content restated.
    flag_indices: list[int]
    summary: str


class FlagConsolidatorAgentOutput(BaseModel):
    groups: list[FlagGroupCandidate]
