# SMG Dev Guide

The agent-native development guide for the [Shepherd Model Gateway](https://github.com/smg-project/smg): six skills that change what a coding agent **does** in the SMG repository, backed by scripts that keep the guide **verifiably in sync** with SMG itself.

Works with **Claude Code** (as a plugin, with hooks), and with **Codex**, **Gemini CLI**, **Google Antigravity** and **Cursor** through the Agent Skills format. SMG's own CI installs this plugin into every automated PR review ([`claude-code-review.yml`](https://github.com/smg-project/smg/blob/main/.github/workflows/claude-code-review.yml)), and SMG's `REVIEW.md` asks reviewers to use `smg:review-pr`.

| Skill | Action | What it does |
|---|---|---|
| `smg:map` | Orient | A **live** crate/subsystem map generated from the checkout you are in, plus the invariants (layering, two-path config, request flow, worker lifecycle, Symphony vs legacy parsers, three transports) and a "where things live" table |
| `smg:implement` | Build | Detects the subsystem, loads one of **21 recipes** (exact paths, code shapes, verification commands per step), and records what the recipe got wrong |
| `smg:review-pr` | Review | Maps changed files to checklist sections and reports `REVIEW.md`-severity findings with `file:line` |
| `smg:contribute` | Ship | Runs the whole pre-PR gate as **one command** (`scripts/gate.sh`) and spells out the branch/commit/PR rules SMG's CI enforces |
| `smg:learn` | Improve | Records a lesson (stale path, missing step, unpredicted CI failure) as a structured issue the next sync promotes |
| `smg:sync` | Maintain | Resyncs the guide against SMG HEAD: drift report → fixes → zero broken anchors → bump the verified commit → PR |

Verified against SMG `176ce3ae` (v1.13.0, 2026-10-29) — see [`smg-ref.json`](smg-ref.json). Every recipe carries its own `verified` commit and `level`.

## How the guide stays true

Hard-coded facts about a codebase that merges dozens of PRs a day rot in weeks. This repository treats every path, symbol, CLI flag and CI lane a skill mentions as an **anchor** into SMG, and checks them:

```
  agent in SMG hits a wrong step ──/smg:learn──▶ issue labelled `lesson`
                                                        │
  daily drift.yml: check_anchors.py + upstream_digest   │
  against SMG main ──▶ "Guide drift report" issue       │
                                                        ▼
                              /smg:sync (human or claude-code-action)
                              fix skills · promote lessons · 0 broken anchors
                              bump smg-ref.json · PR "docs: resync skills with smg HEAD"
                                                        │
  PR CI: lint_guide.py + check_anchors.py against the pinned SMG commit ◀┘
```

- **`scripts/check_anchors.py`** extracts anchors straight from the Markdown (nothing to maintain by hand), resolves them against an SMG checkout (paths, `git ls-files`; symbols/flags/lanes, whole-word search), and fails on anything missing. Placeholders and intentional negatives live in `anchors/ignore.txt`.
- **`scripts/upstream_digest.sh`** summarises what changed in SMG since the pin: commits by type and scope, crates and directories added or removed, renamed files, and churn per recipe (each recipe's `watch` list).
- **`scripts/lint_guide.py`** checks the guide's own plumbing (recipe references, front matter, symlinks, manifests, hooks, provenance, evals) on every PR.
- **`scripts/map_live.sh`** feeds the `map` skill from the checkout instead of a table that goes stale.
- **`evals/`** holds routing/knowledge cases for `claude plugin eval` ("support model X" must go to the Symphony recipe, a stale path must trigger `learn`).
- **Hooks** (Claude Code): a `SessionStart` banner says which SMG version you are in and how far it is from the pin, and a `PreToolUse` guard blocks what SMG's CI would reject later — unsigned commits, Claude/anthropic attribution trailers, `--no-verify`, commits on `main`, pushes from badly named branches.

## Install

### Claude Code

```bash
claude plugin marketplace add smg-project/smg-dev-guide
claude plugin install smg@smg-dev-guide
```

Or inside Claude Code: `/plugin marketplace add smg-project/smg-dev-guide` then `/plugin install smg@smg-dev-guide`, and `/reload-plugins`. The plugin ships skills, the `/smg:go` router command, the `smg-reviewer` subagent, and the hooks above (they are no-ops outside SMG and smg-dev-guide checkouts).

### Codex

Codex discovers skills from `.agents/skills/`:

```bash
git clone https://github.com/smg-project/smg-dev-guide.git ~/.agents/repos/smg-dev-guide
mkdir -p ~/.agents/skills
ln -s ~/.agents/repos/smg-dev-guide/.agents/skills/* ~/.agents/skills/
```

Or clone it into the SMG repo root and the `.agents/skills/smg-*` links are picked up there. Invoke with `$smg-implement`, `$smg-contribute`, etc., or let them trigger on your prompt.

### Gemini CLI

```bash
gemini skills install https://github.com/smg-project/smg-dev-guide.git            # global
gemini skills install https://github.com/smg-project/smg-dev-guide.git --scope workspace
```

### Google Antigravity

Open this repository (or copy `.agents/` and `skills/` into the SMG project root) and the workflows in `.agents/workflows/` appear as slash commands: `/map`, `/implement-feature`, `/review-pr`, `/verify-pr`, `/record-lesson`, `/sync-guide`. For a global install, clone to `~/.gemini/antigravity/repos/smg-dev-guide` and symlink `.agents/workflows/*` and `skills/*` into `~/.gemini/antigravity/{workflows,skills}/`.

### Cursor

Install as a Cursor plugin via `.cursor-plugin/plugin.json`.

### Scripts on other runtimes

The skills reference `${CLAUDE_PLUGIN_ROOT}/scripts/...`. Outside Claude Code, run the same scripts from your smg-dev-guide checkout: `scripts/gate.sh` and `scripts/map_live.sh` locate the SMG checkout from the current directory or an argument.

## Usage

```
/smg:map where does the label pipeline live        → orient (live map + invariants)
/smg:implement add a --timeout flag                → recipe-driven build
/smg:review-pr 562                                 → checklist review
/smg:contribute                                    → run scripts/gate.sh, fix FAILs, ship
/smg:learn                                         → record a lesson about the guide
/smg:sync                                          → maintainers: resync against SMG HEAD
/smg:go <anything>                                 → routes to the right skill
```

Skills also trigger on plain prompts ("am I ready to submit?" → `contribute`).

## Recipes (`skills/implement/recipes/`)

| Recipe | Subsystem |
|---|---|
| config-plumbing | CLI flags, config fields, the two-path rule, validation, Python chain |
| routing-policy | `LoadBalancingPolicy`, factory + registry, load feed |
| symphony-format | **New model support**: a Symphony format table (the default parser) |
| tool-parser, reasoning-parser | the legacy per-model parsers (`--parser legacy`) |
| bindings-update | Python PyO3 + Go FFI |
| discovery-feature | K8s / Consul / file / Slurm providers behind one reconciler, label pipeline |
| grpc-backend | gRPC engine clients, the `Mode`-parameterized pipeline |
| zmq-backend | same-host `ipc://` engines: wire crate, engine adapter, gateway seam |
| storage-backend | data connectors, migrations, hooks |
| wasm-plugin | WASM middleware guests and the host |
| auth-feature | serving-path API keys, control-plane JWT/OIDC |
| observability-feature | metrics, tracing, logging, bounded label interners |
| mesh-feature | SWIM gossip, CRDT namespaces |
| mcp-feature | approval policies, transports |
| kv-index-feature | radix trees, the event-driven chain index, cache-aware selection |
| multimodal-feature | vision processors and model specs |
| provider-api | third-party provider routers (`crates/external_router`), OpenAI-compatible vendors |
| scheduler-feature | priority admission classes, queues, reservations |
| tenancy-feature | tenant identity and resolution |
| rate-limit-feature | the global token bucket and per-tenant limits |

Each recipe starts with front matter: `verified` (the SMG commit it was last checked against), `level` (`full` or `anchors`), and `watch` (the SMG paths whose churn means it needs another look).

## Scripts

| Script | Use |
|---|---|
| `scripts/gate.sh [--fix] [--skip-tests] [--only ...] [--dry-run]` | the pre-PR gate: fmt, clippy, tests, pre-commit, Python/Go lanes, `Cargo.lock`, branch/commit rules; prints a PASS/FAIL table |
| `scripts/map_live.sh [dir]` | live crate map, gateway layout, policies, parser counts, CI lanes |
| `scripts/check_anchors.py --smg <path> [--format text\|json\|markdown] [--paths-only]` | drift detector |
| `scripts/upstream_digest.sh --smg <path> [--since <commit>]` | what changed upstream since the pin, churn per recipe |
| `scripts/lint_guide.py` | the guide's self-consistency check |
| `scripts/hooks/session_start.sh`, `scripts/hooks/guard_bash.py` | the Claude Code hooks |

## Contributing to the guide

1. Branch `feat/…`, `fix/…`, `docs/…`, `chore/…` or `refactor/…`; conventional commit subjects; `git commit -s`; no Claude/anthropic attribution trailers (CI rejects them).
2. A changed skill or recipe must still pass `python3 scripts/lint_guide.py` and `python3 scripts/check_anchors.py --smg <smg checkout>`; cite real paths and symbols, and update the recipe's `verified` / `level` / `watch`.
3. Placeholders (`MyPolicy`) and intentional negatives ("there is no `handle_pod_event`") go in `anchors/ignore.txt` with a comment.
4. Lessons: file an issue labelled `lesson` (what `/smg:learn` does) or add `lessons/YYYY-MM-DD-<slug>.md` from the template. A resync PR promotes and closes them.
5. Keep the skill names: SMG's `REVIEW.md` and review workflow invoke them.

## Repository layout

```
skills/                   the six skills (Agent Skills format)
  map/SKILL.md            + reference.md
  implement/SKILL.md      + recipes/*.md (front matter: recipe, verified, level, watch)
  review-pr/SKILL.md      + anti-patterns.md
  contribute/SKILL.md
  sync/SKILL.md  learn/SKILL.md
scripts/                  gate.sh, map_live.sh, check_anchors.py, upstream_digest.sh, lint_guide.py, lib/, hooks/
hooks/hooks.json          Claude Code hooks (SessionStart banner, PreToolUse git guard)
agents/smg-reviewer.md    isolated-context reviewer subagent
commands/go.md            /smg:go router
anchors/ignore.txt        anchors the checker must not look up
lessons/                  inbox + template for lessons (issues preferred)
evals/                    claude plugin eval cases
smg-ref.json              the SMG commit/version the guide was verified against
.agents/                  skills symlinks + Antigravity workflows (Codex, Gemini CLI, Antigravity)
.claude-plugin/           plugin + marketplace manifests · .cursor-plugin/ Cursor manifest
.github/workflows/        pr-checks.yml (lint + anchors at the pin), drift.yml (daily drift issue, opt-in autosync)
```

## License

Apache-2.0
