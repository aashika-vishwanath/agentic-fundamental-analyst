---
description: Incrementally sync CLAUDE.md against the current state of the codebase — surface and apply only what's materially changed
---

# Sync Rules: Update CLAUDE.md from Codebase Reality

## Objective

Unlike `/create-rules` (which authors CLAUDE.md from scratch against the PRD), this command performs an **incremental diff-and-update**: scan what actually exists in the repo, compare it against what CLAUDE.md currently claims, and apply only the changes that are real and material. It must never regenerate or overwrite the whole file, never silently weaken a Hard Constraint to match code that violates it, and never resolve a contradiction between the codebase and `PRD.md` on its own authority.

**Run this at the end of any session where the codebase or its direction moved forward** — whether or not `/execute` ran to completion. `/execute`'s own Final Verification step already updates CLAUDE.md's Current State when a plan finishes; this command is for everything else (planning sessions that touched files, manual fixes, ad hoc changes, or just a periodic sanity check).

If `CLAUDE.md` doesn't exist yet, stop and suggest `/create-rules` instead — this command has nothing to diff against.

---

## Process

### Phase 1: DISCOVER — inventory current reality

- `git status` and `git log --oneline` since CLAUDE.md was last modified (`git log -1 --format=%cI -- CLAUDE.md`, then `git log --oneline --since=<that date>`) to bound the diff window
- Full directory structure (mirror `/prime`'s approach: tracked files, `tree`-style layout)
- Read `PRD.md` in full — canonical source of intended architecture; CLAUDE.md must never contradict it
- Read `CLAUDE.md` in full — this is the "claimed state" being checked
- Read `pyproject.toml` if it exists — dependencies, Python version, script entry points, test config
- List `.agents/plans/` — which plans exist, and for each, whether its own Completion Checklist is checked off (complete vs. in-flight)
- List what exists under `evals/`, `tests/`, `.agents/references/` — datasets, golden files, filled-in vs. still-stub reference docs
- Check whether Logfire instrumentation is actually present in code (`logfire.configure`, `instrument_pydantic_ai`) if any code exists

### Phase 2: ANALYZE — diff claimed vs. real, and real vs. PRD

Check each CLAUDE.md section against reality:

| CLAUDE.md section | What "stale" looks like |
|---|---|
| Current State | Last-completed-phase claim doesn't match what plans/code show; listed passing eval datasets don't match what exists; Logfire status is wrong |
| Hard Constraints | A constraint is being routinely violated by real code |
| Conventions | Actual file layout, agent definition pattern, prompt convention, or eval naming has diverged from what's documented |
| Commands | Section says "not yet available" but real, runnable commands now exist (or documented commands no longer work) |
| Testing Strategy | A new evaluator type or testing layer is in use but undocumented |
| Observability & Logging | Span/attribute conventions in code differ from what's documented |
| Key Files | Section is empty/stale but entry points, contracts module, agent registry, or eval dirs now exist |
| On-Demand Context | A reference stub got filled in but the pointer table doesn't reflect it, or a new reference doc exists with no pointer |

Separately, check **codebase vs. `PRD.md`** — independent of what CLAUDE.md currently says: has an agent been added, removed, or renamed relative to the PRD §4 roster? Has a data source appeared that isn't in PRD §5? A model tier changed without an eval comparison justifying it (PRD §10)? This is a different class of finding — it's not "CLAUDE.md is stale," it's "reality has drifted from the PRD," and it must be surfaced, not quietly encoded into CLAUDE.md as if it were sanctioned.

### Phase 3: CLASSIFY findings

For each discrepancy found:

- **Factual update** — something objectively changed (a phase completed, a command now exists, a file now exists) → safe to apply directly
- **Convention drift** — code consistently does something CLAUDE.md doesn't document, and it looks intentional/repeated rather than a one-off → apply; if it looks like an accident or a single instance, flag instead
- **Constraint violation** — code contradicts a Hard Constraint → never silently loosen the rule to match the code; report it prominently and let the user decide whether it's a bug to fix or a constraint to reconsider
- **PRD drift** — code, agent roster, or contracts diverge from `PRD.md` → report; do not resolve by editing either file unilaterally
- **Noise** — trivial or one-off, doesn't meet the `create-rules.md` bar of "every rule exists because violating it caused or would cause a real problem" → do not add

### Phase 4: APPLY — targeted edits only

- Edit `CLAUDE.md` incrementally with `Edit`, never rewrite the whole file — everything not being changed must be preserved exactly
- Always update **Current State** if any factual update applies — this section is unconditional (per `execute.md`'s Final Verification step) and should never be allowed to go stale
- Fix pointers in the **On-Demand Context** table if a reference stub is now genuinely filled in elsewhere — don't author new reference *content* here; that belongs to `/execute` or a dedicated writing pass
- Never delete or weaken a Hard Constraint as part of this command
- Keep the `create-rules.md` philosophy: CLAUDE.md stays scannable in under a minute, no content duplicated from `PRD.md` (link instead), every section earns its place

### Phase 5: REPORT

Summarize, don't dump raw diffs:

```markdown
## CLAUDE.md Sync

### Applied
- {section}: {what changed and why}

### Flagged, not applied (needs your call)
- {constraint violation or PRD drift}: {what's inconsistent, where, and the decision it's waiting on}

### Checked, no changes needed
{sections reviewed and found accurate}
```

---

## Guardrails

- Never perform a full `/create-rules`-style regeneration — this command's job is diffing an existing file, not authoring one from scratch
- Never resolve a PRD-vs-code contradiction unilaterally — report and stop
- Never weaken or delete a Hard Constraint to match code that currently violates it
- Never invent Commands or Key Files content — only record what's actually verified to exist and run
