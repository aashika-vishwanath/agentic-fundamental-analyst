---
description: Create a Product Requirements Document for the multi-agent analyst system from conversation
argument-hint: [output-filename]
---

# Create PRD: Generate Product Requirements Document

## Overview

Generate a comprehensive PRD based on the current conversation. This project is a **multi-agent system** (Pydantic AI v2 + Logfire), so the PRD must document things a normal app PRD doesn't: the agent roster, the typed contracts between stages, the agent-vs-deterministic-code boundary, the eval strategy, and the cost/model-routing plan. Adapt depth to what was actually discussed — ask before inventing.

## Output File

Write the PRD to: `$ARGUMENTS` (default: `PRD.md`)

## PRD Structure

### Required Sections

**1. Executive Summary**
- What the system does end to end (input → final artifact)
- Core value proposition and who consumes the output
- MVP goal statement (e.g., "produce a grounded memo for one ticker, one quarter")

**2. Mission & Core Principles**
- Product mission statement
- 3–5 principles. For this project these should include (verbatim or adapted):
  - Agents interpret; deterministic code fetches and computes
  - Every inter-stage boundary is a typed Pydantic model
  - No agent is "done" until it has a labeled eval dataset
  - Absence of data is never a negative signal (`no_data` ≠ bearish)
  - Deterministic evaluators preferred over LLM judges wherever possible

**3. Final Artifact Specification**
- The full structure of the output document (all sections, in order)
- The top-level output model (fields, enums, required evidence/traceability rules)
- What "grounded" means: every quantitative claim must trace to a field in the input bundle

**4. System Architecture**
- Pipeline diagram: fixed deterministic flow with agentic islands
- **Agent roster table** — for each agent: name | role | input type | output type | model tier | capabilities (WebSearch, Thinking, etc.) | agentic loop (yes/no)
- **Deterministic components table** — data layer modules, valuation math, flag consolidation (if deterministic), the pipeline function itself
- Explicit statement of what is NOT an agent and why

**5. Data Layer Specification**
- Source-by-source: API/provider | data obtained | cost (free/paid tier) | cache policy
- Parsing responsibilities (e.g., filing section extraction happens here, not in agents)
- Validation-at-ingest rules and the typed models produced

**6. Data Contracts**
- The core shared models (Flag, verdicts, analyst outputs, the synthesis bundle, the final memo)
- Enum definitions for signals/severities/verdicts
- Optional-field policy for paywalled or unavailable data (`coverage_gaps` propagation)

**7. MVP Scope**
- ✅ In scope / ❌ Out of scope, grouped by: Data Sources, Agents, Evals & Testing, Observability, Orchestration
- Explicitly defer expensive/optional data (e.g., alt data, consensus estimates) with the Optional-field design noted

**8. Evaluation & Testing Strategy** (high level — per-feature detail lives in plan docs)
- Layered approach: golden-file unit tests (data layer) → per-agent eval datasets (Pydantic Evals) → trajectory evals (agentic components) → end-to-end consistency/groundedness evals
- Evaluator preference order: deterministic checks → recall checks → LLMJudge rubrics
- TestModel usage for CI plumbing tests (no API spend in CI)
- What is tracked as a long-run metric but NOT a pass/fail test (e.g., directional hit rate)

**9. Observability Strategy**
- Logfire from first run; one trace per pipeline run; ticker as baggage attribute
- Per-stage spans with custom attributes (flag counts, signals, token cost)
- Dashboards: cost-per-run, latency-per-stage, judge scores over time
- Annotation workflow: disagreements with output → annotated traces → new eval cases (the quality flywheel)

**10. Cost & Model Routing**
- Model tier assignment per agent, with the rule that routing changes must be justified by eval results
- Prompt-caching conventions (stable long content first)
- Spend limits on agentic components

**11. Success Criteria**
- MVP success definition, functional requirements (✅ checkboxes), measurable quality bars (eval scores, groundedness pass rate, cost-per-run ceiling)

**12. Implementation Phases**
- The phase breakdown (data layer → first analyst → remaining analysts → investigator → relative context → synthesis/red-team → hardening), each with: Goal, Deliverables (✅), and Validation criteria (which evals must pass to exit the phase)

**13. Future Considerations**
- Post-MVP: additional data sources, dynamic routing, durable execution, scheduling, multi-ticker screening

**14. Risks & Mitigations**
- 3–5 risks specific to LLM systems: hallucinated figures, over-flagging, sycophantic synthesis, cost blowouts, data-provider drift — each with its concrete mitigation (usually an eval or a deterministic check)

**15. Appendix** (if applicable)
- Repository structure, key dependency links (Pydantic AI docs, Logfire docs, data provider docs)

## Instructions

1. **Extract requirements** from the full conversation history — explicit decisions, agreed contracts, and rationale (the "why" behind agent-vs-code choices matters as much as the choice).
2. **Ask before inventing** — if the agent roster, contracts, or phase boundaries weren't settled in conversation, ask rather than fabricating them.
3. **Write the PRD** with concrete examples: include actual Pydantic model sketches in code blocks, actual enum values, actual API names.
4. **Quality checks:**
   - ✅ Every agent in the roster has input type, output type, and model tier
   - ✅ Every phase has exit criteria expressed as evals/tests that must pass
   - ✅ The agent-vs-deterministic boundary is stated explicitly, not implied
   - ✅ Success criteria are measurable
   - ✅ Consistent terminology (one name per agent/model/stage throughout)

## Output Confirmation

After creating the PRD: confirm the file path, summarize contents briefly, list assumptions made, and suggest next steps (typically `/create-rules`, then `/plan-feature` for the first phase).