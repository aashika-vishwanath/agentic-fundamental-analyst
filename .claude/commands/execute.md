---
description: Execute an implementation plan
argument-hint: [path-to-plan]
---

# Execute: Implement from Plan

## Plan to Execute

Read plan file: `$ARGUMENTS`

## Execution Instructions

### 1. Read and Understand

- Read the ENTIRE plan, plus CLAUDE.md **Hard Constraints** — constraints override the plan if they ever conflict (stop and flag the conflict rather than picking silently)
- Read every file in the plan's "Codebase files to READ" list before writing anything
- Note the plan's Agent-or-Code decisions, contracts, validation ladder, and eval passing bar
- Sanity-check the plan against current code: if the codebase has drifted since planning (renamed models, moved files), reconcile before starting — don't implement against a stale picture

### 2. Execute Tasks in Order

For EACH task in "Step-by-Step Tasks":

**a. Navigate** — identify file + action; read existing related files if modifying

**b. Implement** — follow the spec exactly, and hold the project invariants while doing it:
- Contracts first: import existing models/enums; never redefine or dict-pass across a stage boundary
- Respect the Agent-or-Code decision — if implementation reveals it was wrong (e.g., "this needs no judgment, it's arithmetic"), stop and flag rather than quietly building an agent
- Prompts follow the repo's layout and cache-friendly ordering (stable long content first)
- Type hints throughout; Logfire spans/attributes exactly as the plan's observability section specifies

**c. Validate immediately** — run the task's `VALIDATE` command before moving on. A task isn't done until its command passes.

### 3. Implement the Testing Strategy

Build everything the plan's testing section names — this is a deliverable, not an afterthought:

- Golden-file / unit tests (deterministic, no network)
- TestModel plumbing tests (no API spend)
- **The eval dataset**: every named Case, every evaluator in the plan's preference order (deterministic → recall → LLMJudge), trajectory evals if the component is agentic
- **Never weaken an eval to make it pass** — no deleted cases, no lowered bars, no loosened rubrics. If a case seems wrong, flag it to the user with reasoning and leave it failing.

### 4. Run the Validation Ladder

Execute ALL levels from the plan, in order. On failure: fix, re-run, proceed only on pass.

```bash
# Level 1 — lint / type-check
# Level 2 — unit tests (no network, no keys)
# Level 3 — eval run (must meet the plan's stated passing bar; record scores)
# Level 4 — manual: run the stage on the test ticker; open the Logfire trace and
#           confirm the expected spans, attributes, and cost look healthy
# Level 5 — (if integration touched) full-pipeline smoke run
```

Also run the **existing** eval datasets for adjacent components — the regression check that matters most in this project is "did my change degrade another agent's evals."

### 5. Final Verification

- ✅ All plan tasks complete; each validated at time of implementation
- ✅ Eval dataset exists, registered, and meets the passing bar
- ✅ No regressions in any existing eval dataset or unit suite
- ✅ Deterministic groundedness check present for any LLM output containing figures
- ✅ Logfire trace inspected and matches the plan's observability spec
- ✅ Contracts unchanged except as the plan specifies; reference docs updated if conventions changed
- ✅ **CLAUDE.md's "Current State" section updated — unconditionally, every time**, not only when conventions changed: mark this phase/feature complete, note new eval datasets now passing, and note if Logfire/Commands/Key Files sections need filling in for the first time. This is not optional and is not gated on "did anything change" — the section exists specifically so `/prime` never opens on stale state.
- ✅ **Plan file updated** with any deviations taken and why (the plan is a living record, not a one-way instruction)

## Output Report

### Completed Tasks
- Tasks done; files created/modified (paths)
- Any deviations from plan, with rationale (also written back into the plan file)

### Tests & Evals
- Unit/plumbing tests added and results
- Eval dataset: cases implemented, evaluator list, **scores vs. the passing bar**
- Regression status of pre-existing eval datasets

### Validation Results
```bash
# Output (or summarized output) from each ladder level
```

### Observability & Cost
- Logfire trace link/ID for the manual run
- Observed tokens + cost for the stage; note if materially above the plan's estimate

### Ready for Commit
- Confirm all changes complete, all validations pass, and CLAUDE.md's Current State section reflects this phase → ready for `/commit`

## Notes

- Issues the plan didn't anticipate: document them in the report AND the plan file
- If an eval fails and the *implementation* is at fault → fix implementation until it passes
- If an eval fails and the *case* looks mislabeled → flag to the user; never self-serve the label
- Don't skip ladder levels, and don't substitute a cheaper model tier than the plan assigns without an eval comparison justifying it