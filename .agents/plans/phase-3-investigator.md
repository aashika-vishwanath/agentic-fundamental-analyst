# Feature: The Investigator (Phase 3)

Validate documentation, existing contracts, and codebase patterns before implementing.
Pay special attention to existing model/enum names — import, don't redefine.

## Feature Description

The Investigator is the system's **one and only agentic loop** (PRD §4, and a CLAUDE.md hard
constraint). It takes one `ConsolidatedFlag` — an anomaly the Stage-2 analysts surfaced from the
company's own financials/filings — and investigates it against outside context using Anthropic's
native `web_search` / `web_fetch`, then returns a typed `InvestigationVerdict`: benign, concerning,
or unresolved, with a hypothesis, cited evidence, and a confidence score.

Its defining behavior (PRD §1) is that the *same* anomaly resolves differently depending on
context: an AI-buildout capex spike backed by segment growth is benign; the identical spike
alongside a declining core business is concerning. That judgment cannot come from a threshold — it
has to come from evidence gathered at run time.

## User Story

As the builder, I want each consolidated flag investigated against real outside evidence — gathered
from several independent angles and weighed against each other — so that the memo tells me *why* an
anomaly happened and how confident that reading is, instead of just that a number moved.

## Problem / Solution Statement

**Problem.** Every agent built so far is single-shot over a closed input, which made grounding
mechanical: Phase 1 had the agent index into a closed ratio table; Phase 2 had it quote verbatim
from supplied prose. The Investigator breaks both properties. Its evidence comes from the open web,
which means (a) there is no closed input set to index into, and (b) the agent could fabricate a URL,
a quote, or a conclusion, and nothing upstream would catch it. It is also the first agent that can
burn unbounded money, and the first whose *behavior* (did it actually investigate?) matters as much
as its output.

Four sub-problems, and the decision taken on each:

**1. Grounding evidence from an open-ended source.**
*Chosen:* **URL-provenance grounding.** Anthropic's native web tools return, in the run's own
message history, a `NativeToolReturnPart` per search/fetch whose content carries the real `url` of
every result (verified against the installed adapter — see Research Findings §2). So the closed set
exists after all: it is *the set of URLs the provider actually returned during this run*. Every
`EvidenceCandidate.url` the model emits is checked against that set by deterministic code before it
is promoted to a real `EvidenceItem`; anything else is dropped into `dropped_evidence`. This is the
exact Phase 1/Phase 2 idiom — "drop, don't trust" — applied to the one closed set this agent has.
*Rejected:* trusting the model's citations (no grounding at all); an LLM judge scoring citation
plausibility (violates CLAUDE.md's evaluator-preference order, and can't detect a plausible-looking
fabricated URL).

**2. The user's core constraint: no 1:1 flag → single-source mapping.**
Web search here exists to *inform a judgment*, not to look up one confirming source per flag. Two
mechanisms, because a prompt alone is not checkable:
- **Prompt**: hypothesis-first, multi-angle menu (company's own explanation, independent reporting,
  peer/sector context, macro backdrop, historical precedent), selected per flag rather than
  exhausted every run, with an explicit instruction to search to inform its own judgment and never
  to cherry-pick a source confirming a pre-formed conclusion in *either* direction.
- **Deterministic evaluator** (`MultiAngleInvestigation`): a resolved verdict (benign/concerning)
  requires ≥3 distinct search queries **and** grounded evidence spanning ≥2 distinct registrable
  domains. One-angle investigations are not permitted to resolve — they must return `unresolved`.
  A lazy one-shot investigation therefore **fails the eval**, which is exactly what was asked for.

**3. Confidence must reflect corroboration, not conviction.**
*Chosen:* a deterministic calibration gate (`ConfidenceCalibration`) rather than a judge. Evidence
spanning <2 distinct domains caps `confidence` at 0.5; evidence whose `stance` values conflict
(both `supports_benign` and `supports_concerning` present) caps it at 0.7. The prompt states the
same rule so the model aims at it, but the evaluator is what enforces it.

**4. Cost — this agent can genuinely blow the PRD's ~$2/run ceiling.**
Opus 5 is $5/$25 per 1M tokens and each native search is a further $0.01 flat, with results
accumulating into context and being re-sent every turn (Research Findings §4). A realistic
per-flag cost is **$0.30–$0.55**, so 4+ flags exceed the whole-run budget on this stage alone.
*Chosen:* three stacked caps — `WebSearch(max_uses=6)` / `WebFetch(max_uses=4)` (provider-enforced),
`UsageLimits(request_limit=12, cost_limit=Decimal("0.75"))` (client-enforced, and newly available in
**core** pydantic-ai — see §5, this closes the PRD §10 open question without `pydantic-ai-harness`),
and `Thinking(effort='medium')`. Plus an explicit **investigation budget**: `run_investigations()`
investigates at most `max_investigations` flags (default 5), selected by severity, and emits a
`CoverageGap` for every flag it skipped — never silently dropping one.

**5. Correlated flags (carried forward, not solved here).** Per the pre-planning discussion, the
Investigator receives lightweight sibling-flag summaries (metric/period/description only — no extra
tool calls, no sibling verdicts) so it can *note* a suspected shared root cause in
`correlated_flag_indices`. It does **not** do the weighing. Weighing correlated flags as one story
rather than stacking them as independent negatives is a **Phase 5 Synthesizer** concern; see
Notes → Carried forward to Phase 5.

## Feature Metadata

**Type**: New Capability
**Complexity**: **High** — first agentic loop, first tool-using agent, first open-world grounding
problem, first real cost exposure, and the first agent whose trajectory is part of the contract.
**Pipeline stage(s)**: Stage 4 — consumes `list[ConsolidatedFlag]` from the Flag Consolidator
(Phase 2), produces `list[InvestigationVerdict]` for the Synthesizer (Phase 5).
**Dependencies**: Phase 2 complete (it is). No data-layer changes. No new third-party packages.

## Agent-or-Code Decisions

| Component | Agent or Code | Why |
|---|---|---|
| Hypothesis formation, search-angle selection, verdict, confidence | **Agent** (the loop) | Pure judgment over open-ended evidence — the one thing in this system that genuinely needs a loop |
| Flag → prompt serialization, sibling-summary construction | Code | Deterministic formatting; the model must never restate a flag's structured data |
| URL provenance extraction from message history | Code | Parsing `NativeToolReturnPart`s is mechanical and must be trustworthy — it *is* the grounding check |
| Evidence grounding (`_ground_evidence`) | Code | The whole point is that it isn't the model's word for it |
| Trajectory extraction (queries, domains, fetched URLs) | Code | Feeds both the eval substrate and Logfire attributes |
| Investigation budget / severity selection / skip gaps | Code | A budget the model could negotiate with isn't a budget |
| Verdict aggregation across flags | Code (`asyncio.gather`) | PRD §4: parallel, one run per flag, fixed |

## Data Contracts

New module: `src/agentic_fundamental_analyst/contracts/investigation.py`.

```python
class VerdictType(str, Enum):          # PRD §6 names these exactly
    BENIGN = "benign"
    CONCERNING = "concerning"
    UNRESOLVED = "unresolved"

class EvidenceStance(str, Enum):
    SUPPORTS_BENIGN = "supports_benign"
    SUPPORTS_CONCERNING = "supports_concerning"
    CONTEXT = "context"                 # neither direction; background only

class SiblingFlagSummary(BaseModel):    # code-built, read-only context
    metric: str
    fiscal_year: int
    fiscal_period: str
    description: str

class EvidenceCandidate(BaseModel):     # AGENT-authored — never trusted as-is
    url: str
    claim: str                          # what this source actually says
    stance: EvidenceStance

class InvestigatorAgentOutput(BaseModel):   # the Agent's own output_type
    hypothesis: str
    verdict: VerdictType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[EvidenceCandidate]
    correlated_sibling_indices: list[int]   # 0-based into the sibling list given

class EvidenceItem(BaseModel):          # post-grounding, code-constructed
    url: str
    claim: str
    stance: EvidenceStance

class InvestigationTrajectory(BaseModel):   # code-derived from message history
    search_queries: list[str]
    result_urls: list[str]              # every URL the provider returned
    fetched_urls: list[str]
    distinct_domains: list[str]

class InvestigationVerdict(BaseModel):      # the stage's output
    flag: ConsolidatedFlag                  # reused object, never reconstructed
    verdict: VerdictType
    hypothesis: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem]
    correlated_sibling_indices: list[int]
    trajectory: InvestigationTrajectory
    dropped_evidence: list[str]             # ungrounded URLs — diagnostic
    coverage_gaps: list[CoverageGap]
```

**Deviation from the PRD §6 sketch, and why.** PRD sketches `InvestigationVerdict` with
`evidence: list[str]`. This plan uses structured `EvidenceItem` + a `trajectory` field, because:
(a) a bare string can't be grounded — a URL must be separable from the claim to check it against
what the provider returned; (b) `stance` is what makes the "corroboration, not conviction"
confidence rule deterministically checkable; (c) `trajectory` is the *only* substrate a trajectory
eval can use, since native tool calls emit no spans (§2 below). PRD §6 states its models are
"illustrative, not exhaustive", so this is an extension within its intent, not a contradiction.
`SourcedFigure`/`SourcedQuote`/`Flag`/`ConsolidatedFlag`/`Severity`/`CoverageGap` are all **imported
unchanged** from `contracts/`.

---

## RESEARCH FINDINGS

Verified against the **installed** `pydantic-ai 2.32.0` / `pydantic-evals 2.32.0` source (not just
docs — the repo's `.agents/references/pydantic-ai-v2.md` snapshot is 2.31.1 and predates several of
these). Re-verify §2 and §3 live before trusting them in a paid run.

### 1. `WebSearch` / `WebFetch` capabilities — constructor surface

`pydantic_ai/capabilities/web_search.py`, `web_fetch.py`. Both subclass `NativeOrLocalTool`.

- `WebSearch(native=True, local=None, search_context_size=, user_location=, blocked_domains=,
  allowed_domains=, max_uses=, external_web_access=, ...)`.
- `WebFetch(native=True, local=None, allowed_domains=, blocked_domains=, max_uses=,
  enable_citations=, max_content_tokens=, ...)`.
- `_requires_native()` returns True when `max_uses` (or domain filters) are set — i.e. **setting
  `max_uses` forces native mode**, which is what we want; there is no silent DuckDuckGo downgrade.
- Anthropic natively supports both (`native_tools/__init__.py` lists Anthropic first for
  `WebSearchTool`; `models/anthropic.py` maps both to `Beta*Tool*Param`).
- `WebSearchTool.kind == 'web_search'`; `WebFetchTool.kind == 'web_fetch'` — these are the exact
  `tool_name` values on the message parts, and what the trajectory extractor must match on.
- Anthropic accepts **either** `allowed_domains` **or** `blocked_domains`, never both (400).

### 2. ⚠️ Native tool calls emit **no** tool spans — the built-in trajectory evaluators will not see them

This is the single most important finding in this research, and it invalidates the obvious approach.

`pydantic_evals/evaluators/agentic.py::_is_tool_call_span()` matches only **locally-executed** tool
spans (it requires a `gen_ai.tool.name` attribute on a span named `running tool` / `execute_tool …`).
Anthropic's web search and web fetch are **provider-executed**: pydantic-ai receives them as
`NativeToolCallPart` / `NativeToolReturnPart` message parts (`part_kind='builtin-tool-call'` /
`'builtin-tool-return'`), recorded in OTel as *message-part entries on the chat span* with a
`builtin: true` marker (`pydantic_ai/_otel_messages.py`), **not** as their own spans.

**Consequence:** `ToolCorrectness`, `MaxToolCalls`, `TrajectoryMatch`, `ArgumentCorrectness`, and a
span-query `HasMatchingSpan` on tool names **would all silently report zero tool calls** for this
agent. PRD §8's literal "`HasMatchingSpan` to assert it searched" is not implementable as written.

**Therefore:** trajectory evaluation reads `result.all_messages()` and inspects
`NativeToolCallPart` / `NativeToolReturnPart` directly. `run_investigator()` extracts this into the
typed `InvestigationTrajectory` at run time, so evaluators assert against a typed field rather than
re-parsing message internals. `HasMatchingSpan` is still used, but only for what it *can* see —
that the `investigator_stage` span and a model-request span exist.

### 3. What the native tools return — the grounding substrate

`models/anthropic.py::_map_web_search_tool_result_block()` / `_map_web_fetch_tool_result_block()`:

- **Search** → `NativeToolReturnPart(tool_name='web_search', content=[...])` where each result is
  `{url, title, page_age, encrypted_content, type}` (confirmed against
  `anthropic.types.beta.BetaWebSearchResultBlock.model_fields`).
- **Fetch** → `NativeToolReturnPart(tool_name='web_fetch', content={content, retrieved_at, type, url})`
  (confirmed against `BetaWebFetchBlock.model_fields`).
- The matching **call** part is `NativeToolCallPart(tool_name='web_search', args={'query': ...})` —
  this is where `search_queries` comes from.

So real URLs are present and typed. That is what makes URL-provenance grounding possible.

⚠️ **Error shape, from the Anthropic docs**: a failed server tool returns HTTP 200 with `content`
as a single **error object** (`{"type": "web_search_tool_result_error", "error_code": ...}`) instead
of a **list** of results. The extractor must branch on that — `isinstance(content, list)` — or it
will crash on a rate-limited run. Error codes: `too_many_requests`, `max_uses_exceeded`,
`query_too_long`, `request_too_large`, `unavailable`, `invalid_tool_input`.
⚠️ **`web_fetch` only fetches URLs already present in the conversation** (Anthropic docs) — it
cannot invent a URL to fetch, which reinforces the grounding model rather than fighting it.
⚠️ **`pause_turn`**: long search turns can return `stop_reason: "pause_turn"`; pydantic-ai handles
continuation, but it means wall-clock latency per investigation is genuinely variable.

### 4. Thinking + structured output on Opus 5 — verified compatible (this was a real risk)

`models/anthropic.py::prepare_request()` raises `UserError` when extended thinking is combined with
**output tools** (which is what a Pydantic `output_type` compiles to by default). Verified against
the actual profile via `pydantic_ai.profiles.anthropic.anthropic_model_profile('claude-opus-5')`:

| flag | claude-opus-5 |
|---|---|
| `anthropic_supports_adaptive_thinking` | `True` |
| `anthropic_supports_forced_tool_choice` | `True` |
| `anthropic_disallows_budget_thinking` | `True` |
| `supports_json_schema_output` | `True` |

The guard is `thinking_blocks_output_tools = (type=='enabled') or (type=='adaptive' and not
supports_forced_tool_choice)` → for Opus 5 that is `False or (True and not True)` = **False**, so
**no error**: `Thinking(...)` and a structured `output_type` coexist on Opus 5.
`_translate_thinking()` maps the unified setting to `{'type': 'adaptive'}` (never `budget_tokens`,
which Opus 5 rejects with a 400), and `anthropic_effort` **falls back to the unified thinking effort
level** — so `Thinking(effort='medium')` really does set `output_config.effort`, giving genuine cost
control. Haiku 4.5, by contrast, has `anthropic_supports_adaptive_thinking=False` — do **not** add
`Thinking` to the Flag Consolidator without re-checking this.

### 5. Cost, and the PRD §10 spend-limit question — answerable from core now

Authoritative pricing (Anthropic docs, fetched this phase):
- **Claude Opus 5** (`claude-opus-5`): **$5.00 / 1M input, $25.00 / 1M output**, 1M context.
- **Web search: $10 per 1,000 searches** ($0.01 each), *plus* token cost for results, which count as
  input tokens on that turn **and every subsequent turn of the run**.
- Claude Sonnet 5: $3/$15 ($2/$10 intro pricing through 2026-08-31). Haiku 4.5: $1/$5.

Per-flag estimate with `max_uses=6`: ~6 searches ($0.06) + roughly 40–90K cumulative input tokens
across ~5–10 model requests ($0.20–0.45) + a few K output ($0.05–0.13) ≈ **$0.30–0.55 per flag**.

**`UsageLimits` is in core `pydantic-ai` and now carries a real cost cap** —
`UsageLimits(cost_limit: Decimal | None, request_limit: int|None = 50, tool_calls_limit,
input_tokens_limit, output_tokens_limit, total_tokens_limit, ...)`. This **closes open question #1**
in `.agents/references/pydantic-ai-v2.md` (which concluded `SpendLimits` needed the separate
`pydantic-ai-harness` package): a per-run USD cap needs no extra dependency. Note `tool_calls_limit`
counts *local* tool calls, so it will read 0 here — `max_uses` on the capability is the real cap on
searches.

### 6. Sources

- Installed source: `pydantic_ai/capabilities/{web_search,web_fetch,thinking}.py`,
  `pydantic_ai/models/anthropic.py`, `pydantic_ai/native_tools/__init__.py`,
  `pydantic_ai/messages.py`, `pydantic_ai/_otel_messages.py`, `pydantic_ai/usage.py`,
  `pydantic_evals/evaluators/agentic.py`, `pydantic_evals/otel/span_tree.py`.
- [Anthropic web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
  — parameters, result shape, error codes, `pause_turn`, $10/1,000 pricing.
- [Anthropic web fetch tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool)
  — `max_content_tokens`, citations, URL-must-be-in-conversation rule.
- [Anthropic pricing](https://docs.claude.com/en/docs/about-claude/pricing).

---

## CONTEXT REFERENCES

### Codebase files to READ before implementing

- `src/agentic_fundamental_analyst/agents/flag_consolidator.py` (whole file, 93 lines) — **the
  closest structural analog**: index-based grounding, `_resolve_groups()` drop-don't-trust pattern,
  stage span with signal attributes, short-circuit on empty input.
- `src/agentic_fundamental_analyst/agents/financial_statements.py` — the candidate → grounded-output
  split (`*AgentOutput` vs `*Output`) this phase mirrors, and `coverage_gaps` construction.
- `src/agentic_fundamental_analyst/agents/grounding.py` (24 lines) — the shared prose-grounding
  helper; Phase 3 adds a *sibling* module, it does not modify this one.
- `src/agentic_fundamental_analyst/contracts/{consolidation,flags,sourcing}.py` — import
  `ConsolidatedFlag`, `Flag`, `Severity`; do not redefine.
- `src/agentic_fundamental_analyst/contracts/financials.py:6` — `CoverageGap` is defined **here**
  (not in `financial_analyst.py`, which merely imports it). Reuse it; do not redefine.
- `src/agentic_fundamental_analyst/agents/models.py` — add `INVESTIGATOR_MODEL` here, never inline.
- `evals/flag_consolidator.py` (whole file) — dataset shape, `@dataclass` custom `Evaluator`
  subclasses, `metadata`-keyed recall checks, `__main__` runner block.
- `tests/unit/test_flag_consolidator_agent.py` — `TestModel(custom_output_args=...)` scripting and
  the "empty input never calls the model" test idiom.
- `.agents/references/agents.md` §"Grounding for prose input" — the two existing grounding
  mechanisms this one is the third of.

### New files to create

- `src/agentic_fundamental_analyst/contracts/investigation.py` — all contracts above.
- `src/agentic_fundamental_analyst/agents/investigator.py` — the agent, `run_investigator()`,
  `run_investigations()`.
- `src/agentic_fundamental_analyst/agents/provenance.py` — `extract_trajectory()`,
  `ground_evidence()`, `registrable_domain()`. Deterministic, model-free, unit-testable in
  isolation — this is the module that makes the whole design checkable.
- `evals/investigator.py` — dataset + the four evaluators.
- `tests/unit/test_provenance.py` — pure-function tests over hand-built message lists.
- `tests/unit/test_investigator_agent.py` — `TestModel`/`FunctionModel` plumbing tests.

### Documentation to READ before implementing

- [Anthropic web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
  — §Response (exact result-block shape), §Errors (the list-vs-object branch), §Usage and pricing.
- [Anthropic web fetch tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool)
  — the "URL must already be in the conversation" constraint.
- [pydantic-ai capabilities](https://pydantic.dev/docs/ai/core-concepts/capabilities/) and
  [WebSearch](https://pydantic.dev/docs/ai/capabilities/web-search/) — re-verify constructor kwargs
  against 2.32.0 before writing.
- `.agents/references/pydantic-ai-v2.md` §2 (capabilities), §3 (evals), §4 (TestModel/FunctionModel)
  — **but note** it is a 2.31.1 snapshot; Research Findings above supersede it on native-tool spans,
  the agentic evaluators, and `UsageLimits.cost_limit`.

### Patterns to follow

Agent definition + capabilities + limits (extends the Phase 2 shape):

```python
investigator = Agent(
    INVESTIGATOR_MODEL,
    name="investigator",
    output_type=InvestigatorAgentOutput,
    instructions=_INSTRUCTIONS,
    capabilities=[
        Thinking(effort="medium"),
        WebSearch(max_uses=6),
        WebFetch(max_uses=4, max_content_tokens=8000),
    ],
)

result = await investigator.run(
    prompt,
    usage_limits=UsageLimits(request_limit=12, cost_limit=Decimal("0.75")),
)
```

Stage span with signal attributes (mirrors `flag_consolidator.py:85-92`):

```python
with logfire.span("investigator_stage", metric=..., severity=...) as span:
    ...
    span.set_attribute("verdict", verdict.value)
    span.set_attribute("confidence", confidence)
    span.set_attribute("search_count", len(trajectory.search_queries))
    span.set_attribute("distinct_domain_count", len(trajectory.distinct_domains))
    span.set_attribute("dropped_evidence_count", len(dropped))
```

Drop-don't-trust grounding (mirrors `flag_consolidator.py::_resolve_groups`):

```python
def ground_evidence(
    candidates: list[EvidenceCandidate], returned_urls: set[str]
) -> tuple[list[EvidenceItem], list[str]]:
    grounded, dropped = [], []
    for c in candidates:
        if _normalize_url(c.url) in returned_urls:
            grounded.append(EvidenceItem(url=c.url, claim=c.claim, stance=c.stance))
        else:
            dropped.append(c.url)
    return grounded, dropped
```

---

## IMPLEMENTATION PLAN

### Phase A: Contracts & provenance primitives
`contracts/investigation.py` with every model above. `agents/provenance.py` with
`extract_trajectory(messages)`, `ground_evidence(candidates, urls)`, `registrable_domain(url)`,
`_normalize_url(url)`. No agent code yet — these are pure functions and get unit-tested first.

### Phase B: The agent
`agents/investigator.py`: `_INSTRUCTIONS`, the `Agent` instance with capabilities, prompt
construction (flag first for cache-friendliness, then siblings, then the task), `run_investigator()`
doing run → extract trajectory → ground evidence → apply the unresolved-on-thin-evidence rule →
build `InvestigationVerdict`.

### Phase C: Fan-out + integration
`run_investigations(flags, max_investigations=5)`: severity-ordered selection, `asyncio.gather`
across the chosen flags, sibling summaries built per flag from the *other* flags, `CoverageGap` per
skipped flag. `INVESTIGATOR_MODEL` in `agents/models.py`. Stage spans throughout. `pipeline.py` is
still Phase 5 — this exposes the callable, it does not wire the pipeline.

### Phase D: Evals & validation
`evals/investigator.py` with the two canonical capex cases plus a clean case and a
thin-evidence case, and the four evaluators. Unit tests for provenance and agent plumbing.

---

## STEP-BY-STEP TASKS

### CREATE `src/agentic_fundamental_analyst/contracts/investigation.py`
- **IMPLEMENT**: every model in Data Contracts above, in that order.
- **PATTERN**: `contracts/consolidation.py` (agent-output vs resolved-output split),
  `contracts/flags.py` (enum style).
- **IMPORTS**: `ConsolidatedFlag` from `.consolidation`; `CoverageGap` from
  `agentic_fundamental_analyst.contracts.financials` (verified — that is where it is defined;
  `financial_analyst.py:5` imports it from there). Do **not** redefine it.
- **GOTCHA**: `(str, Enum)` is this repo's convention (ruff `UP042` is ignored project-wide for it).
  `confidence` must carry `Field(ge=0.0, le=1.0)` — an out-of-range confidence should be a
  validation error, not a silent bad score.
- **VALIDATE**: `uv run pyright src/agentic_fundamental_analyst/contracts/investigation.py`

### CREATE `src/agentic_fundamental_analyst/agents/provenance.py`
- **IMPLEMENT**: `_normalize_url` (strip fragment, strip trailing slash, lowercase scheme+host,
  keep query — two different query strings are two different pages); `registrable_domain` (host,
  minus a leading `www.`); `extract_trajectory(messages) -> InvestigationTrajectory` walking
  `ModelResponse.parts` for `NativeToolCallPart`/`NativeToolReturnPart` with
  `tool_name in {'web_search', 'web_fetch'}`; `ground_evidence(...)` as sketched above.
- **PATTERN**: `agents/grounding.py` — small, pure, no imports from agent modules.
- **IMPORTS**: `from pydantic_ai.messages import ModelMessage, ModelResponse, NativeToolCallPart,
  NativeToolReturnPart`.
- **GOTCHA (critical)**: a web-search `NativeToolReturnPart.content` is a **list** of result dicts on
  success but a single **error dict** on failure (Research §3) — branch on `isinstance(content, list)`
  or the extractor crashes on any rate-limited run. Web-*fetch* content is a single dict with `url`
  even on success. Both may legitimately be absent/malformed: never raise from the extractor, return
  what parsed.
- **GOTCHA**: match on `tool_name`, not `part_kind` alone — MCP and other native tools share the
  `builtin-tool-*` part kinds.
- **VALIDATE**: `uv run pytest tests/unit/test_provenance.py -q`

### CREATE `tests/unit/test_provenance.py`
- **IMPLEMENT**: hand-built `list[ModelMessage]` fixtures covering — a successful search with 3
  results; a search error object (`max_uses_exceeded`); a `web_fetch` return; a fabricated URL that
  must be dropped; a URL differing only by trailing slash/fragment that must still ground; two URLs
  on the same registrable domain counting as **one** distinct domain; `www.` vs bare host.
- **PATTERN**: `tests/unit/test_grounding.py`.
- **GOTCHA**: no model, no network, no `TestModel` — these are pure-function tests and must stay so.
- **VALIDATE**: `uv run pytest tests/unit/test_provenance.py -q`

### UPDATE `src/agentic_fundamental_analyst/agents/models.py`
- **IMPLEMENT**: `INVESTIGATOR_MODEL = "anthropic:claude-opus-5"` with a comment noting Opus tier is
  PRD §4 roster, and that Research §4 verified adaptive-thinking + output-tool compatibility.
- **VALIDATE**: `uv run ruff check src`

### CREATE `src/agentic_fundamental_analyst/agents/investigator.py`
- **IMPLEMENT**: `_INSTRUCTIONS`; the `Agent`; `_build_prompt(flag, siblings)`;
  `run_investigator(flag, siblings) -> InvestigationVerdict`; `run_investigations(flags,
  max_investigations=5) -> list[InvestigationVerdict]`.
- **PATTERN**: `agents/flag_consolidator.py` end to end.
- **IMPORTS**: `from pydantic_ai.capabilities import Thinking, WebFetch, WebSearch`;
  `from pydantic_ai.usage import UsageLimits`; `from decimal import Decimal`;
  `from agentic_fundamental_analyst import config, observability  # noqa: F401`.
- **The prompt must state** (these are the user's constraints, and each has a matching evaluator):
  1. Form a hypothesis *before* searching; search to test it.
  2. Investigate from **more than one angle** — the menu (company's own explanation / independent
     reporting / peer-sector context / macro backdrop / historical precedent), choosing what fits
     *this* flag rather than exhausting all five.
  3. Search to inform your own judgment. **Never** cherry-pick a source that confirms a pre-formed
     conclusion in either direction; report evidence that cuts against your hypothesis too.
  4. Confidence reflects **corroboration**, not conviction: multiple independent sources agreeing
     raises it; a single source, or sources that conflict, lowers it.
  5. `unresolved` is a **correct and expected** answer when evidence is thin or contradictory —
     do not force benign/concerning. (Mirrors Phase 1/2's "raising zero flags is permitted".)
  6. Cite only URLs that actually appeared in your search results; a citation you can't point at
     will be dropped.
  7. Note in `correlated_sibling_indices` any sibling flag that plausibly shares a root cause with
     this one — by **index only**, never restating its content.
- **GOTCHA**: sibling summaries are context, **not** targets — state explicitly that the verdict must
  be about *this* flag only.
- **GOTCHA**: put the flag + siblings first in the prompt and keep `_INSTRUCTIONS` static, per
  CLAUDE.md's cache-friendly ordering convention.
- **GOTCHA**: `run_investigations([])` must return `[]` **without constructing a span or calling the
  model** — same structural guarantee as the Transcript Analyst's `None` short-circuit.
- **GOTCHA**: apply the thin-evidence rule in **code**, not by trusting the model: if grounded
  evidence spans <2 distinct domains, force `verdict=UNRESOLVED` and cap `confidence` at 0.5, and
  record a `CoverageGap` explaining it. The model is told the rule; code enforces it.
- **VALIDATE**: `uv run pytest tests/unit/test_investigator_agent.py -q`

### CREATE `tests/unit/test_investigator_agent.py`
- **IMPLEMENT**: (1) `TestModel` produces a valid `InvestigatorAgentOutput`; (2) a scripted
  `custom_output_args` run where a fabricated URL is dropped and a real one survives — by injecting
  a message history via a `FunctionModel` that emits `NativeToolCallPart`/`NativeToolReturnPart`;
  (3) empty-flag-list short-circuit with **no** model override installed (proves no model call);
  (4) `max_investigations` budget produces a `CoverageGap` per skipped flag and never drops one
  silently; (5) thin-evidence forcing to `unresolved`.
- **PATTERN**: `tests/unit/test_flag_consolidator_agent.py`.
- **GOTCHA**: `TestModel` **cannot emulate provider-executed native tools** (docs, §4 of the
  reference). Either override with `native_tools=[]` or use `FunctionModel` to script the parts —
  verify which override kwarg 2.32.0 accepts before writing, and if neither works cleanly, fall back
  to testing `run_investigator`'s grounding path through `provenance.py` directly (already covered)
  and keep the agent test to output-type plumbing only.
- **GOTCHA**: `tests/conftest.py` already sets `ALLOW_MODEL_REQUESTS=False` — a missing override
  fails loudly rather than spending money. Do not weaken it.
- **VALIDATE**: `uv run pytest tests/unit -q` (all 89 existing + new must pass)

### CREATE `evals/investigator.py`
- **IMPLEMENT**: dataset + four evaluators (see Testing Strategy).
- **PATTERN**: `evals/flag_consolidator.py` — `@dataclass` `Evaluator` subclasses, `metadata`-keyed
  expectations, `__main__` block calling `dataset.evaluate_sync(...)`.
- **GOTCHA**: this dataset makes **real web searches and real Opus calls**. Put the per-run cost
  (~$0.30–0.55/case) in the module docstring, as `evals/flag_consolidator.py` documents its bar.
- **GOTCHA**: any `LLMJudge` must be pinned to `model=INVESTIGATOR_MODEL` — the repo has already
  been bitten once by `LLMJudge` defaulting to an OpenAI model and crashing key-free
  (`.agents/references/evals.md`).
- **VALIDATE**: `uv run python -m evals.investigator`

### UPDATE `.agents/references/agents.md`, `evals.md`, `observability.md`, `CLAUDE.md`
- **IMPLEMENT**: Investigator sections — the third grounding mechanism (URL provenance), the
  native-tools-emit-no-spans finding and what it forced, the new span/attribute set, measured cost.
  Update CLAUDE.md Current State per its mandatory-update rule.
- **GOTCHA**: `.agents/references/pydantic-ai-v2.md` open question #1 (`SpendLimits` needs the
  harness package) is now **answered** — `UsageLimits.cost_limit` is in core. Update it there too.
- **VALIDATE**: `uv run ruff check .`

---

## TESTING STRATEGY

### Unit tests (deterministic, CI-safe, zero API spend)
`test_provenance.py` (the substantive suite — every grounding and trajectory rule, as pure functions
over hand-built message lists) and `test_investigator_agent.py` (plumbing: output type, budget,
short-circuit, thin-evidence forcing). Existing 89 tests must stay green.

### Eval dataset (`evals/investigator.py`)

**Cases** — inputs are `ConsolidatedFlag`s built from realistic fixture `Flag`s:

| Case | Scenario | Expectation |
|---|---|---|
| `capex_spike_ai_buildout_benign` | Large-cap capex/D&A spike, growing cloud segment (PRD §11 canonical case #1) | `verdict == BENIGN` |
| `capex_spike_declining_core_concerning` | Same magnitude spike, shrinking core business (canonical case #2) | `verdict == CONCERNING` |
| `obscure_microcap_thin_evidence_unresolved` | Real but barely-covered issuer — the web genuinely can't resolve it | `verdict == UNRESOLVED`, **not** forced either way; the over-reach guard |
| `routine_disclosure_benign` | A flag with a mundane, well-documented explanation | resolves cleanly at low search cost — the over-investigation guard |

Two canonical cases are PRD §11 exit criteria; the other two are this dataset's clean/negative
guards (per the repo's every-dataset-has-one convention).

**Evaluators, in CLAUDE.md's required preference order:**

1. **Deterministic — hard gates, 100% required:**
   - `EvidenceProvenanceEvaluator` — every `EvidenceItem.url` in the output appears in
     `trajectory.result_urls`, re-derived independently rather than trusting `run_investigator`
     applied `ground_evidence` correctly. Exactly the independence principle the Phase 2 grounding
     evaluators already follow.
   - `MultiAngleInvestigation` — **the user's constraint, made mechanical**: a `BENIGN`/`CONCERNING`
     verdict requires ≥3 distinct `search_queries` **and** ≥2 distinct `distinct_domains`. A
     one-search, one-source investigation cannot pass. `UNRESOLVED` is exempt (it's the honest
     answer to thin evidence).
   - `ConfidenceCalibration` — <2 distinct domains ⇒ `confidence ≤ 0.5`; conflicting stances present
     ⇒ `confidence ≤ 0.7`. Corroboration, not conviction.
2. **Recall** — `ExpectedVerdict`: `metadata['expected_verdict']` matches `output.verdict`. This is
   what the two canonical capex cases actually turn on.
3. **`LLMJudge` — one, narrowly scoped**: does `reasoning` weigh evidence *against* itself (note
   what cuts against the hypothesis) rather than restating one source? Judge only what no
   deterministic check can reach — pinned to `model=INVESTIGATOR_MODEL`.

**Trajectory evals** — per Research §2, implemented as deterministic assertions over the typed
`InvestigationTrajectory`, **not** `ToolCorrectness`/`MaxToolCalls` (which cannot see native tools):
- `MultiAngleInvestigation` above *is* the trajectory eval that matters.
- `MaxSearchBudget`: `len(search_queries) <= 6`, matching `WebSearch(max_uses=6)` — catches a
  runaway loop.
- `HasMatchingSpan(query=SpanQuery(name_equals='investigator_stage'))` — the one span assertion that
  *is* valid, confirming the stage span exists.

**Passing bar**: all three deterministic gates at 100% across all 4 cases; `ExpectedVerdict` 4/4
(both canonical cases are PRD exit criteria and are not negotiable); `LLMJudge` ≥3/4, with the
Phase 2 precedent that a single judge miss on otherwise-grounded output is investigated and
documented, **never** silenced by loosening the rubric.

### Edge cases
Search returns an error object rather than results (rate limit / `max_uses_exceeded`); zero search
results; model cites a plausible but fabricated URL; model cites a URL it *fetched* but never
*searched*; all evidence from one domain; conflicting evidence; `pause_turn` mid-run; a flag whose
`ConsolidatedFlag.flags` has several members (summary vs per-flag detail); empty flag list; more
flags than `max_investigations`; `cost_limit` tripping mid-run (must surface as a `CoverageGap`,
never a silent partial verdict).

---

## VALIDATION COMMANDS
Run every level; zero regressions required.

### Level 1: Syntax & style
`uv run ruff check .` and `uv run pyright src tests evals`

### Level 2: Unit tests
`uv run pytest tests/unit -q` — **89 existing + new must all pass**.

### Level 3: Evals
`uv run python -m evals.investigator` — bar as stated above. Also re-run all Phase 1/2 datasets
(`evals.financial_statements`, `evals.filings`, `evals.transcripts`, `evals.flag_consolidator`) to
confirm no regression from the shared-contract changes.

### Level 4: Manual — real ticker + trace inspection
Run the full Stage-2 chain on a real ticker (GOOGL is already live-verified and reliably produces a
multi-year `capex_to_depreciation_ratio` flag), feed the consolidated flags to `run_investigations`,
then inspect Logfire for: an `investigator_stage` span per investigated flag; nested model-request
spans with populated `gen_ai.usage.*` / `operation.cost`; `verdict` / `confidence` / `search_count`
/ `distinct_domain_count` / `dropped_evidence_count` attributes present. **Record the real per-flag
cost** — this is the number that decides whether Opus survives PRD §11's ~$2/run ceiling.

### Level 5: Cost sanity
Sum `operation.cost` across one full multi-flag run and compare against the ~$2 ceiling. If a
5-flag run exceeds it, the options — in preference order — are: lower `max_investigations`; lower
`WebSearch(max_uses)`; drop `Thinking` effort to `low`; only then consider Sonnet 5 for the
Investigator, which must be justified by an eval-score delta on this dataset (PRD §10), not by
intuition.

---

## ACCEPTANCE CRITERIA
- [ ] Contracts match plan exactly; no untyped boundaries introduced
- [ ] All validation levels pass; eval bar met
- [ ] Deterministic groundedness in place: **no evidence URL survives that the provider didn't return**
- [ ] Multi-angle rule enforced deterministically — a one-source investigation cannot return a
      resolved verdict
- [ ] Confidence calibration enforced deterministically, not by judge
- [ ] Logfire trace shows `investigator_stage` spans with cost + signal attributes
- [ ] Spend caps active at all three layers (`max_uses`, `UsageLimits`, `max_investigations`)
- [ ] Every skipped/failed investigation surfaces a `CoverageGap` — never a silent omission
- [ ] No regressions in the four existing eval datasets
- [ ] CLAUDE.md + reference docs updated (incl. correcting `pydantic-ai-v2.md` open question #1)

## COMPLETION CHECKLIST
- [ ] Tasks executed in order, each validation passed immediately
- [ ] Full unit suite + all existing evals pass
- [ ] Manual trace inspection done; real per-flag cost recorded
- [ ] Plan file updated with any deviations taken during implementation

---

## EXECUTION DEVIATIONS

Two real bugs were caught during live eval validation (real Opus 5 + real web search), not by any
unit test written up front — both are now fixed and covered by free regression tests that would have
caught them, but are recorded here since they changed the shipped implementation from what this plan
originally specified.

**1. Domain-diversity check was keyed on the wrong thing.** The original implementation passed
`len(trajectory.distinct_domains)` (every domain any raw `web_search` call *returned*, including
irrelevant SEO noise) into `_apply_multi_angle_rule` and into `evals/investigator.py`'s
`MultiAngleInvestigation`/`ConfidenceCalibration`. Live-caught on the `obscure_microcap_thin_evidence_unresolved`
case: a search for a deliberately fictional company returned **32 distinct raw domains** of pure
noise despite finding nothing real — meaning a model that cherry-picked one source could have passed
the diversity gate purely on search-engine noise, exactly the loophole the user's original
constraint ("no one-to-one mapping of flag to a single confirming source") was meant to close. Fixed
by deriving domain diversity from `{registrable_domain(e.url) for e in evidence}` — the domains of
evidence the model actually *cited*, not what the search API happened to return. Regression test:
`test_run_investigator_forces_unresolved_despite_many_raw_search_domains` (7 raw noise domains, 1
cited domain → still forces `unresolved`; fails under the old logic, passes under the new).

**2. `UsageLimitExceeded` crashed instead of degrading.** `run_investigator` had no handling around
the `investigator.run(...)` call, so a budget overrun raised an unhandled exception. Live-caught on
`routine_disclosure_benign` when a real investigation's cumulative cost hit `$0.79` against the
`$0.75` cap. Inside `pydantic_evals`'s own per-case exception handling this only showed up as a
`Case Failure`, but inside `run_investigations`'s `asyncio.gather(*(_investigate(f) for f in
selected))` (no `return_exceptions=True`), the same exception would have cancelled every other
flag's concurrently-running investigation — one expensive flag would have silently destroyed a whole
run's worth of otherwise-completed work. Fixed with a `try/except UsageLimitExceeded` that returns a
degraded `InvestigationVerdict` (`unresolved`, confidence `0.0`, empty evidence, a `CoverageGap`
naming the budget overrun) instead of propagating. Regression test:
`test_run_investigator_degrades_gracefully_when_usage_budget_exceeded` (monkeypatches
`_INVESTIGATOR_USAGE_LIMITS` to `request_limit=1` to force the real exception path, not a mock).

**Real cost data (4 live runs total, ~$7 spent across eval iterations + 1 GOOGL pipeline run):**
per-case cost ranged **$0.357–$1.14**, averaging **~$0.45–0.60**, noticeably above this plan's
original $0.30–0.55 estimate on the high end — the `capex_spike_declining_core_concerning` (Intel)
case in particular needed genuinely more multi-source research (Intel + AMD + TSMC + Samsung + CHIPS
Act) than the other three, and its input tokens reached **~199K** in one run (vs. ~60–80K for the
others) as accumulated search-result context compounded across turns. Re-run of that single case in
isolation resolved correctly at `$0.573` — confirming the earlier miss was cost variance on a
legitimately harder investigation, not a defect. **The `$0.75` per-flag `cost_limit` is left as
planned, not raised**, per user decision: this is exactly the spend-limit calibration question PRD
§10/§12 already assigns to Phase 6, and the real distribution captured here (rather than a guess) is
what that phase should tune against.

**Dynamic filtering risk (flagged as unverified in Research Findings §"Dynamic filtering") — resolved.**
Live runs confirm `trajectory.result_urls`/`fetched_urls` come through populated and correctly
grounded (e.g. 11/11 evidence items grounded, zero dropped, on the real GOOGL Level 4 run) — Opus
5's `web_search_20260209` dynamic-filtering variant does not hide result URLs from the client. No
fallback to the basic tool variant was needed.

**Level 4 result (real GOOGL run, 2026-08-19).** Full Stage-2/3 chain end to end: Financial
Statements Analyst → 5 raw flags; Filings Analyst → 0; Transcript Analyst → 0 (no span emitted,
correctly, per its structural no-transcript guarantee); Flag Consolidator → 1 consolidated flag (the
same multi-year `capex_to_depreciation_ratio` escalation, 2.40x→4.33x 2021–2025, seen in Phase 2's
own live run); Investigator → `benign`, confidence `0.70`, 11 grounded evidence items across 6
queries, 0 dropped, 0 coverage gaps. The investigation's hypothesis correctly separated two distinct
causes rather than taking the ratio at face value: a disclosed AI/data-center capex program, *and* a
January 2023 accounting-estimate change (extended server useful life to six years) that mechanically
suppresses the ratio's denominator independent of any change in real spending. Span hierarchy
confirmed exactly as designed: `investigator_stage` → `investigator run` → `chat claude-opus-5`,
nested correctly alongside the other four stages' spans in one trace.

## NOTES

**Trade-offs taken.**
- *Structured evidence over PRD's `list[str]`* — costs a little contract surface, buys deterministic
  grounding and a checkable confidence rule. Justified in Data Contracts.
- *Code-enforced thin-evidence → `unresolved`* — the model could be merely instructed, but this
  system's whole idiom is "never trust the model to self-police what code can check."
- *`max_investigations=5`* — a real product limitation (a 9-flag company gets its 4 lowest-severity
  flags uninvestigated). Made visible as `CoverageGap`s rather than hidden, per the never-coerce-
  missing-data constraint. Revisit once real cost is measured.

**Deferred / open.**
- Prompt-cache effectiveness across investigations is unmeasured; the instructions block is static
  and the flag varies, so cache hits should be modest. Worth a Logfire look in Phase 6.
- `search_context_size` is left at the provider default; tuning it is a cost lever if Level 5 shows
  a problem.
- ~~Dynamic filtering: unverified whether `web_search_20260209`'s nested result blocks come through
  to the client.~~ **Resolved during execution** — see EXECUTION DEVIATIONS above; result URLs come
  through populated and grounded correctly across every live run.

**Carried forward to Phase 5 (Synthesizer / Red-Team)** — from the pre-planning discussion:
- Correlated flags that share one root cause must be weighed as **one story with several data
  points**, never stacked as independent negatives. The Investigator supplies the raw signal
  (`correlated_sibling_indices`); the Synthesizer must act on it.
- The Synthesizer's rubric should weigh by verdict confidence and by whether evidence sources are
  genuinely independent — not by counting flags.
- Red-Team gets a **standing attack category**: "did the draft double-count correlated flags as
  independent negatives?" — so the failure mode is checked structurally rather than trusted to the
  draft pass.

**Cost note for CLAUDE.md.** The Filings Analyst was the previous per-call cost leader at
$0.13–0.28. The Investigator is expected to exceed that *per flag*, and is the first stage where
cost scales with input complexity (flag count) rather than being roughly fixed per run.
