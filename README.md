# SMG Dev Guide

The agent-native development guide for the [Shepherd Model Gateway](https://github.com/smg-project/smg): seven skills that change what a coding agent **does** in the SMG repository, grounded in SMG's own code and history, and kept **verifiably in sync** with it by scripts.

Works with **Claude Code** (as a plugin, with hooks and subagents), and with **Codex**, **Gemini CLI**, **Google Antigravity** and **Cursor** through the Agent Skills format. SMG's own CI installs this plugin into every automated PR review ([`claude-code-review.yml`](https://github.com/smg-project/smg/blob/main/.github/workflows/claude-code-review.yml)), and SMG's `REVIEW.md` asks reviewers to run `smg:review-pr`.

| Skill | Use it to | First read |
|---|---|---|
| `smg:map` | orient: a **live** crate map read from the checkout, the seven invariants, the area table (path → recipe → review checklist) | 60 lines + the live map |
| `smg:implement` | build: a detection table routes to one of **27 recipes**; every step has a file, a verify command and the silent trap; exemplar commits show the full file set a real change touched | 60 lines + a recipe (~100) |
| `smg:craft` | write it the way the maintainers do: vocabulary (sides, role, pool), performance discipline, interface design, structure; four evidence-backed references | 50 lines |
| `smg:review-pr` | review: changed files map to per-subsystem checklists (with anti-patterns); error handling, testing and craft always apply; REVIEW.md markers with `file:line` | 70 lines + matched checklists |
| `smg:contribute` | ship: the whole pre-PR gate as **one command** (`scripts/gate.sh`) that also prints the CI lanes a diff triggers and checks vocabulary | 55 lines |
| `smg:learn` | record a lesson (stale path, missing step, unpredicted CI failure) as an issue the next sync promotes | |
| `smg:sync` | maintainers: resync the guide against SMG HEAD (drift, coverage, digest, lessons → PR) | |

Verified against SMG `176ce3ae` (v1.13.0): 3,000+ anchors, 0 broken ([`smg-ref.json`](smg-ref.json)). Every recipe carries its own `verified` commit, `level`, `watch` paths and `exemplars`.

## How the guide stays true

Hard-coded facts about a codebase that merges dozens of PRs a day rot in weeks. Three checkers and one data file keep this guide honest:

- **`scripts/check_anchors.py`**: every path, symbol, flag and CI lane the skills cite is extracted from the Markdown and verified against an SMG checkout. Zero maintenance; placeholders and stated negatives live in `anchors/ignore.txt`.
- **`scripts/check_coverage.py`**: for each recipe, recent `feat(...)` commits touching its `watch` paths (plus its listed `exemplars`) are read, and the areas at least half of them touch but the recipe never mentions are reported. "Names exist" is the floor; "matches what PRs touch" is the bar.
- **`scripts/check_vocabulary.py`**: flags the terms SMG rejects (PD "leg", a dispatch "arm", per `CONTRIBUTING.md`) and generated-sounding filler, over a diff, commit messages, or the guide's own prose.
- **`data/subsystems.json`**: one row per area (paths, owner, recipe, review checklists, CI lanes, key types). `scripts/render.py` writes it into the skills between markers; `scripts/lanes.py` maps a diff to lanes and checklists for the gate. `data/rules.json` holds the naming and attribution regexes once, for the gate, the hook and the contribute skill.

```
  agent in SMG hits a wrong step ──/smg:learn──▶ issue labelled `lesson`
                                                        │
  daily drift.yml: anchors + coverage + digest          │
  against SMG main ──▶ "Guide drift report" issue       │
                                                        ▼
                              /smg:sync (human or claude-code-action)
                              fix skills · promote lessons · 0 broken anchors
                              bump smg-ref.json · PR "docs: resync skills with smg HEAD"
                                                        │
  PR CI: lint_guide.py (template, data, render, vocabulary) + check_anchors.py at the pin ◀┘
```

**Hooks** (Claude Code): a SessionStart banner names the SMG version you are in and its drift from the pin; a PreToolUse guard blocks what SMG's CI would reject later (unsigned commits, Claude/anthropic attribution trailers, `--no-verify`, commits on `main`, pushes from badly named branches). **Subagents**: `smg-reviewer` (isolated-context review) and `smg-scout` (where/how questions and history mining without flooding the main context).

## Install

### Claude Code

```bash
claude plugin marketplace add smg-project/smg-dev-guide
claude plugin install smg@smg-dev-guide
```

Or inside Claude Code: `/plugin marketplace add smg-project/smg-dev-guide`, `/plugin install smg@smg-dev-guide`, `/reload-plugins`. `/smg:go <request>` routes to the right skill.

### Codex

```bash
git clone https://github.com/smg-project/smg-dev-guide.git ~/.agents/repos/smg-dev-guide
mkdir -p ~/.agents/skills && ln -s ~/.agents/repos/smg-dev-guide/.agents/skills/* ~/.agents/skills/
```

Or clone it into the SMG repo root; the `.agents/skills/smg-*` links are picked up there. Invoke with `$smg-implement`, `$smg-craft`, etc.

### Gemini CLI

```bash
gemini skills install https://github.com/smg-project/smg-dev-guide.git            # global
gemini skills install https://github.com/smg-project/smg-dev-guide.git --scope workspace
```

### Google Antigravity

Open this repository (or copy `.agents/` and `skills/` into the SMG project root): the workflows in `.agents/workflows/` appear as `/map`, `/implement-feature`, `/craft`, `/review-pr`, `/verify-pr`, `/record-lesson`, `/sync-guide`.

### Cursor

Install as a Cursor plugin via `.cursor-plugin/plugin.json`.

### Scripts on other runtimes

Skills reference `${CLAUDE_PLUGIN_ROOT}/scripts/...`. Elsewhere, run the same scripts from your checkout of this repository; `gate.sh`, `map_live.sh` and `lanes.py` find the SMG checkout from the current directory.

## For the SMG repository itself

`upstream/smg/` holds drafts a maintainer can apply to SMG: an `AGENTS.md` (the invariants stated nowhere upstream, the commands, what CI rejects), a `CLAUDE.md` that imports it, and five-line `//!` headers for the four entry files that have none. `bash upstream/smg/apply.sh <smg checkout>`.

## Recipes (`skills/implement/recipes/`)

config-plumbing · routing-policy · symphony-format (new model support) · tool-parser, reasoning-parser (legacy lane) · tokenizer · bindings-update · http-endpoint · protocols-profile · discovery-provider · discovery-feature · grpc-backend · zmq-backend · engine-servicer · storage-backend · wasm-plugin · auth-feature · observability-feature · mesh-feature · mcp-feature · kv-index-feature · multimodal-feature · provider-api · scheduler-feature · tenancy-feature · rate-limit-feature · e2e-lane

One shape for all: front matter (`verified`, `level`, `watch`, `exemplars`), a four-line context, Inputs, numbered Steps (`File` · `Do` · `Verify` · `Trap`), Rules. `scripts/lint_guide.py` enforces it.

## Scripts

| Script | Use |
|---|---|
| `scripts/gate.sh [--fix] [--skip-tests] [--only ...] [--dry-run]` | the pre-PR gate: fmt, clippy, tests, pre-commit, Python/Go lanes, `Cargo.lock`, vocabulary, branch/commit rules, lanes; PASS/FAIL table |
| `scripts/map_live.sh [dir]` | live crate map, gateway layout, policies, parser counts, CI lanes |
| `scripts/lanes.py [files]` | which areas, recipes, review checklists and CI lanes a diff touches |
| `scripts/check_anchors.py --smg <path>` | drift detector (paths, symbols, flags, lanes) |
| `scripts/check_coverage.py --smg <path> [--show recipe]` | exemplar coverage per recipe |
| `scripts/check_vocabulary.py [--diff] [--commits RANGE] [files]` | banned terms and generated-sounding prose |
| `scripts/upstream_digest.sh --smg <path>` | what changed upstream since the pin, churn per recipe |
| `scripts/render.py [--check]` | write `data/*.json` into the skills |
| `scripts/lint_guide.py` | the guide's self-consistency check (runs on every PR) |

## Contributing to the guide

1. Branch `feat/…`, `fix/…`, `docs/…`, `chore/…` or `refactor/…`; conventional subjects; `git commit -s`; no Claude/anthropic attribution trailers (CI rejects them; the plugin's own hook does too).
2. Edit `data/subsystems.json` or `data/rules.json`, then `python3 scripts/render.py`; never edit a rendered block by hand.
3. A changed recipe keeps the template and passes `python3 scripts/lint_guide.py`, `python3 scripts/check_anchors.py --smg <smg>` and, ideally, `python3 scripts/check_coverage.py --smg <smg> <recipe>`; update its `verified`, `level`, `watch`, `exemplars`.
4. Placeholders (`<name>`, in angle brackets) and stated negatives go in `anchors/ignore.txt` with a comment; vocabulary rules in `data/vocabulary.json`.
5. Keep the skill names: SMG's `REVIEW.md` and review workflow invoke them.

## Repository layout

```
skills/                    map (+reference.md) · implement (+recipes/) · craft (+writing, performance, interface, structure)
                           review-pr (+checklists/) · contribute · sync · learn
data/                      subsystems.json · rules.json · vocabulary.json
scripts/                   gate.sh · map_live.sh · lanes.py · check_anchors.py · check_coverage.py · check_vocabulary.py
                           upstream_digest.sh · render.py · lint_guide.py · rules.py · lib/ · hooks/
hooks/hooks.json           SessionStart banner · PreToolUse git guard
agents/                    smg-reviewer · smg-scout
commands/go.md             /smg:go router
upstream/smg/              AGENTS.md, CLAUDE.md and module-doc drafts for the SMG repo
anchors/ignore.txt · lessons/ · evals/ · smg-ref.json
.agents/                   skills links (smg-*) + Antigravity workflows · .claude-plugin/ · .cursor-plugin/
.github/workflows/         pr-checks.yml (lint + anchors at the pin) · drift.yml (daily drift issue, opt-in autosync)
```

## License

Apache-2.0
