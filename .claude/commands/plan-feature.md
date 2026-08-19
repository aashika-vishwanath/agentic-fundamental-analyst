---
description: "Create a comprehensive implementation plan for a phase/feature of the analyst system"
---

# Plan a Phase / Feature

## Feature: $ARGUMENTS

## Mission

Transform a discussed phase or feature into a **context-rich implementation plan** that an execution agent can complete in one pass. We do NOT write code in this phase.

For this project, a plan is incomplete unless it answers four questions no generic template asks:
1. **Agent or code?** — for each new component, is it an agent (interpretation) or deterministic code (fetching/math)? Justify.
2. **What are the contracts?** — the exact Pydantic input/output models, including enums and Optional-field policy.
3. **How is it evaluated?** — the eval dataset design comes *with* the feature, not after it.
4. **What will Logfire show?** — the spans/attributes this feature emits and what "healthy" looks like in a trace.

## Planning Process

### Phase 1: Feature Understanding
- Core problem, user value, feature type (New Capability / Enhancement / Refactor / Bug Fix), complexity (Low/Med/High)
- Which pipeline stage(s) this touches; what upstream contracts it consumes and downstream contracts it must produce
- Refine or write the user story: `As a <user> I want <action> so that <benefit>`

### Phase 2: Codebase Intelligence
- Read CLAUDE.md constraints and the PRD sections for this phase
- Read the contracts module — reuse existing models/enums before defining new ones
- Find the closest existing analog (e.g., a new analyst should mirror the first analyst's structure, prompt layout, and eval scaffolding)
- Identify test patterns: where golden files live, how eval datasets are registered, how TestModel plumbing tests are written
- Check `.agents/reference/` docs relevant to the touched area
- **Clarify ambiguities with the user now** — especially contract fields, enum values, and eval expectations

### Phase 3: External Research

Delegate to research subagents where beneficial (framework, provider, and domain research are independent — run them in parallel). Regardless of who does the research, **the findings must land in the plan** — links with section anchors, captured payloads, chosen formulas with sources. "See the docs" is not a finding.

- **Pydantic AI**: consult the installed Pydantic AI skill first — it is the primary source for capability usage (Evals, Thinking, WebSearch/WebFetch, SpendLimits, instrumentation). Fetch live docs only for gaps or version-specific behavior the skill doesn't cover, and note the version checked.
- **Data-provider APIs** (no skill covers these — always research fresh): endpoints, auth, rate limits, response shapes for any new API touched. **Capture a real sample response into the golden-files directory** as part of planning; the plan references it by path.
- **Domain research** if needed (e.g., which earnings-quality screens, which valuation formulas), with sources cited in the plan.

### Phase 4: Strategic Thinking
- Where can this component hallucinate, over-flag, or silently degrade — and which evaluator catches each failure mode?
- Cost: expected tokens per run, model tier choice (and which eval comparison would justify a cheaper tier)
- What happens on missing data / provider errors? (`no_data` propagation, Optional fields, retries)
- Cache implications: what gets cached, what busts the prompt cache

### Phase 5: Generate the Plan

**Filename**: `.agents/plans/{kebab-case-name}.md` (create dir if needed)

Fill this template:

```markdown
# Feature: <name>

Validate documentation, existing contracts, and codebase patterns before implementing.
Pay special attention to existing model/enum names — import, don't redefine.

## Feature Description
<what and why>

## User Story
As a <user> I want <action> so that <benefit>

## Problem / Solution Statement
<problem this solves; approach chosen and alternatives rejected, with rationale>

## Feature Metadata
**Type**: [...]  **Complexity**: [...]  **Pipeline stage(s)**: [...]  **Dependencies**: [...]

## Agent-or-Code Decisions
| Component | Agent or Code | Why |
|---|---|---|

## Data Contracts
<exact Pydantic models this feature consumes and produces — full field lists, enums, Optional policy>

---

## CONTEXT REFERENCES

### Codebase files to READ before implementing
- `path/file.py` (lines X–Y) — Why: pattern to mirror
...

### New files to create
- `path/new_file.py` — purpose
...

### Documentation to READ before implementing
- [Doc](url#anchor) — section; why needed
...

### Patterns to follow
<actual code snippets from this repo: agent definition, prompt layout, eval registration, golden-file test>

---

## IMPLEMENTATION PLAN

### Phase A: Contracts & Data
<models, fixtures, golden files, any data-layer additions>

### Phase B: Core Implementation
<the agent/module itself: prompt, capabilities, model tier, or the deterministic logic>

### Phase C: Integration
<wiring into the pipeline function; span/attribute emission; config>

### Phase D: Evals & Validation
<see Testing Strategy below — built here, not deferred>

---

## STEP-BY-STEP TASKS
(Atomic, ordered, each with a validation command. Use CREATE/UPDATE/ADD/REMOVE/REFACTOR/MIRROR keywords.)

### {ACTION} {target_file}
- **IMPLEMENT**: ...
- **PATTERN**: file:line
- **IMPORTS**: ...
- **GOTCHA**: ...
- **VALIDATE**: `command`

---

## TESTING STRATEGY

### Unit tests (deterministic, CI-safe)
<golden-file tests for any parsing/math; TestModel plumbing tests for agent wiring — no API spend>

### Eval dataset (Pydantic Evals)
- **Cases** (name each): inputs source, expected outputs/flags. Include at least one clean/negative case (catches over-flagging).
- **Evaluators**, in preference order:
  - Deterministic: <e.g., groundedness — every number in output exists in input>
  - Recall: <expected categories/flags present>
  - LLMJudge rubric(s): <exact rubric text or pointer>
- **Trajectory evals** (agentic components only): <e.g., searched before concluding; tool-call budget; cited sources exist in fetch history>

### Edge cases
<missing data, provider errors, amended filings, empty sections, etc.>

---

## VALIDATION COMMANDS
Run every level; zero regressions required.

### Level 1: Syntax & style — `<lint/typecheck commands>`
### Level 2: Unit tests — `<pytest command scoped to this feature>`
### Level 3: Evals — `<eval run command>` (state the passing bar, e.g., "groundedness 100%, recall ≥ N/M cases")
### Level 4: Manual — <run pipeline stage on ticker X; inspect output and the Logfire trace: expected spans/attributes>
### Level 5 (optional): <full-pipeline smoke run if integration touched>

---

## ACCEPTANCE CRITERIA
- [ ] Contracts match plan exactly; no untyped boundaries introduced
- [ ] All validation levels pass; eval bar met
- [ ] Deterministic groundedness check in place for any LLM output containing figures
- [ ] Logfire trace shows expected spans with cost attributes
- [ ] No regressions in existing eval datasets
- [ ] CLAUDE.md / reference docs updated if conventions changed

## COMPLETION CHECKLIST
- [ ] Tasks executed in order, each validation passed immediately
- [ ] Full unit suite + all existing evals pass
- [ ] Manual trace inspection done
- [ ] Plan file updated with any deviations taken during implementation

## NOTES
<trade-offs, deferred items, cost observations>
```

## Quality Criteria

- **Context completeness**: passes the No-Prior-Knowledge test — someone new could implement from the plan alone
- **Contracts explicit**: no "define a model for X" tasks; the fields are in the plan
- **Evals designed up front**: cases and evaluators named before code exists
- **Every task validatable**: non-interactive executable command per task
- **Pattern consistency**: mirrors existing agents/modules; no reinvented utils

## Report

After creating the plan: summary of approach, full path to plan file, complexity assessment, key risks, and a confidence score (#/10) for one-pass success.