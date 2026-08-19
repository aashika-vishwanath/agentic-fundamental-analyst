

Create rules · MD
---
description: Create global rules (CLAUDE.md) for the multi-agent analyst project
---
 
# Create Global Rules
 
Generate a CLAUDE.md by analyzing the codebase and PRD. CLAUDE.md is loaded into context on **every** session, so it must stay lean: constraints, conventions, commands, and pointers. Anything long-form goes in `.agents/reference/` and gets a one-line pointer here (progressive disclosure).
 
---
 
## Phase 1: DISCOVER
 
### Read the source of truth
- Read `PRD.md` — the agent roster, contracts, phases, and principles defined there are canonical; CLAUDE.md must not contradict it.
- Read `pyproject.toml` — dependencies, Python version, script entry points, test config.
- Map the directory structure: where do agents, data-layer modules, contracts/models, evals, golden files, and reference docs live?
### Identify what exists vs. what's planned
- Which phases are built? Which eval datasets exist? Is Logfire wired up?
- Check `.agents/plans/` for completed/in-flight feature plans.
---
 
## Phase 2: ANALYZE
 
Extract from existing code (or from the PRD if pre-code):
 
- **Boundary rules**: which components are agents vs. deterministic code
- **Contract conventions**: where Pydantic models live, enum style, Optional-field policy for missing data
- **Naming**: agent names, module names, eval dataset naming, golden-file naming
- **Prompt conventions**: system-prompt location/structure, cache-friendly ordering (stable content first)
- **Testing layout**: unit tests vs. eval datasets vs. CI plumbing tests (TestModel)
- **Model tier assignments** per agent and where they're configured
- **Logging/observability**: Logfire setup location, span/attribute conventions
---
 
## Phase 3: GENERATE
 
**Output path**: `CLAUDE.md` (project root)
 
### Required sections
 
**1. Project Overview** — 2–3 sentences: what the system produces and the pipeline shape (fixed deterministic flow, agentic islands). Link to PRD.md for detail.
 
**2. Hard Constraints** — the rules the coding agent must never violate. Include (adapted to what the PRD actually says):
- Never wrap data fetching or arithmetic in an agent; agents interpret only
- Every inter-stage boundary is a typed Pydantic model — no dict-passing between stages
- No new agent or prompt change ships without its eval dataset passing
- Never delete or weaken an eval case to make a run pass; flag it instead
- `no_data` / `coverage_gaps` must propagate — never coerce missing data into a signal
- All LLM figures in outputs must be traceable to input-bundle fields
- No API keys in code; environment variables only
**3. Conventions**
- Contracts/models location and style
- Agent definition pattern (where Agent objects live, how model tiers are assigned)
- Prompt file conventions and cache-friendly ordering
- Eval dataset and golden-file conventions
**4. Commands** — exact, runnable:
- Run the pipeline for one ticker
- Run unit tests (data layer / plumbing, no API spend)
- Run a specific agent's eval dataset; run all evals
- Lint / type-check
- Refresh cached data / macro brief
**5. Testing Strategy (high level)**
- The layer map: golden-file tests → per-agent evals → trajectory evals → end-to-end evals
- What runs in CI (TestModel plumbing, deterministic checks) vs. what runs on demand (LLM evals)
- Rule of thumb: deterministic evaluator > recall check > LLMJudge
**6. Observability & Logging Strategy**
- Logfire is instrumented from the first run; one trace per pipeline run
- Span/attribute conventions (ticker baggage, per-stage cost attributes)
- When to check traces (any eval regression, any cost anomaly)
**7. Key Files** — entry point, pipeline function, contracts module, agent registry, eval directories
 
**8. On-Demand Context (progressive disclosure)** — the pointer table:
 
| When working on... | Read first |
|---|---|
| Data layer / parsers / APIs | `.agents/reference/data-layer.md` |
| Any agent's prompt or output contract | `.agents/reference/agents.md` |
| Eval datasets or evaluators | `.agents/reference/evals.md` |
| Logfire spans, dashboards, annotations | `.agents/reference/observability.md` |
| Valuation math | `.agents/reference/valuation.md` |
 
(Create stub reference files for any that don't exist yet; keep CLAUDE.md itself free of the detail they hold.)
 
### Keep it lean
- Target: scannable in under a minute
- No duplication of PRD content — link instead
- Remove any template section that doesn't apply
---
 
## Phase 4: OUTPUT
 
```markdown
## Global Rules Created
 
**File**: `CLAUDE.md`
**Reference stubs created**: {list}
 
### Constraints captured
{bullet list}
 
### Commands verified
{which commands were actually run to confirm they work}
 
### Next Steps
1. Review CLAUDE.md; tighten or remove anything that doesn't earn its context cost
2. Fill in reference docs as each area gets built
3. Add a rule here every time the coding agent does something it shouldn't do again
```
 
---
 
## Tips
 
- CLAUDE.md is for *constraints and pointers*, not documentation
- Every rule should exist because violating it caused (or would cause) a real problem
- Update it as phases complete — stale commands are worse than no commands
 
