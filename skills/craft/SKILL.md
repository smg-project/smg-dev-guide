---
name: craft
description: How SMG code is written, so a change reads like the maintainers wrote it. Use before writing non-trivial code, naming things, designing a flag, metric, endpoint or error, touching a hot path, writing a commit message, PR text or doc comment, or when reviewing for cloning, bounds, duplication and wording. Points to the evidence-backed references on writing, performance, interfaces and structure.
---

# Craft in SMG

The house style is not taste: each rule below names what breaks when it is skipped. The four references in this directory carry the evidence (paths, lines, commits); read the one your change touches.

## Non-negotiables (first read)

1. **Vocabulary.** A disaggregated dispatch has two **sides** (`PdSide`, `PrefillBound`, `DecodeBound`); a worker has a **role** (`WorkerRole::{Single, Prefill, Decode}`); the workers of one role are a **pool**. "Leg" meant all three at once and is not used in code, comments, test names or log lines; a dispatch "arm" is as vague. Metric names keep their published spelling. (`CONTRIBUTING.md`)
2. **Agents.** You own the PR, not the agent; paste real gate output, not "I ran the tests"; no AI attribution anywhere. (`CONTRIBUTING.md`, enforced by the hooks and CI.)
3. **The hot path owns nothing twice.** Request bodies move by value and die with the `RequestLease`; upstream bodies are sized and capped; per-token work clones nothing; server-controlled label values go through `intern_string`, client-controlled ones (model ids, tool names) through the bounded `intern_model_label` / `intern_tool_label` in `crates/external_router/src/metrics.rs` (`MAX_MODEL_LABELS`, then the `other` sentinel); overload is a latched flag, not a per-request walk. (`performance.md`)
4. **Spell it once.** A closed enum gets every arm and no wildcard; a table is written from one list (`tables!`); a surface that exists in two places is pinned by a parity test (CLI ↔ launcher ↔ Helm, registry ↔ README); glue is re-exported, not copied. (`structure.md`)
5. **An operator-facing surface is designed, not added.** A flag has a group, a typed parser, a default and a disabling zero, an alias when renamed, a validation error that names field, value and reason, and its launcher and chart twins; a metric has the `smg_` prefix and a unit suffix; a shed carries `Retry-After`. (`interface.md`)
6. **Prose states facts.** Commit subjects say what changed and why in a full sentence; doc comments state what a module promises; test names read as sentences; no generated-sounding filler ("robust", "seamless", "leverage"). (`writing.md`; `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_vocabulary.py" --diff` over your diff)

## Read when

| Your change | Read |
|---|---|
| names a thing, writes a commit, a PR body, a doc comment or a test | `writing.md` |
| touches request handling, streaming, selection, an index, a cache, a lock | `performance.md` |
| adds or changes a flag, config field, metric, log line, error response, health probe, protocol type | `interface.md` |
| adds a module, a backend, an enum variant, a test, or copies something that exists | `structure.md` |

## Before you push

- `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_vocabulary.py" --diff < <(git diff origin/main...HEAD)` and `--commits origin/main..HEAD`: zero error-level hits (the gate's `vocab` row runs both).
- The review questions at the end of each reference, applied to your own diff.
