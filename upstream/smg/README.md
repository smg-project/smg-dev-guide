# Drafts for the SMG repository

Files the guide cannot land itself (this repository has no write access to `smg-project/smg`), drafted for a maintainer to apply:

| File | Purpose |
|---|---|
| `AGENTS.md` | the orientation every coding agent gets without installing anything: the invariants stated nowhere upstream, the commands, what CI rejects, the plugin. Under 80 lines on purpose (Claude Code recommends keeping project instructions under 200 lines). |
| `CLAUDE.md` | imports `AGENTS.md` with `@AGENTS.md`, so Claude Code and Codex read one file. Claude Code reads `AGENTS.md` on its own only when no `CLAUDE.md` exists, hence both. |
| `module-docs/*.header` | five-line `//!` headers for `model_gateway/src/main.rs`, `config/mod.rs`, `server.rs` and `app_context.rs`: the four entry files with no module doc, which is exactly where the guide's map has to repeat itself. |
| `apply.sh` | copies the two files and prepends the headers (skips a file that already has a `//!` doc). |

Apply from a clean SMG branch:

```bash
bash upstream/smg/apply.sh /path/to/smg
cd /path/to/smg && cargo +nightly fmt --all && git diff --stat
git checkout -b docs/agent-orientation && git commit -s -am "docs: orient coding agents (AGENTS.md, entry-file module docs)"
```

`AGENTS.md` is anchor-checked like a skill (`python3 scripts/check_anchors.py --smg <smg>` scans `upstream/`), so its paths and symbols are verified against the pinned commit on every guide PR. Keep it in step with `skills/map/SKILL.md`'s invariants; both change together in a resync.

## Upstream documentation that is stale (found 2026-10-29 at `176ce3ae`)

Candidates for small docs PRs to SMG and smg-docs, not for the guide:

- `crates/reasoning_parser/src/README.md`: uses `initial_in_reasoning` (the field is `always_in_reasoning`, `traits.rs`), a `max_buffer_size` of 65536, and `src/reasoning_parser/...` paths.
- `crates/mcp/README.md`: documents a `transform/` module that `crates/mcp/src` no longer has.
- smg-docs `contributing/development.md` repository layout: lists `mesh_discovery/`, `tenant.rs` and `rl_adapter.rs`; the code has `mesh/discovery/`, `tenant/` and no `rl_adapter.rs`.
- `REVIEW.md` domain knowledge: "the gRPC pipeline has 10 constructors in pipeline.rs"; at `176ce3ae` there is one `RequestPipeline::build(endpoint, mode, deps)` over eight endpoints and three modes.
- `Cargo.toml` `[workspace.lints]` comment on `allow_attributes`: "92 existing violations"; the tree has 16 `#[allow]` sites, all in tests, benches and the test harness.
- smg-docs `concepts/routing/pd-disaggregation.md` still says "leg" throughout; the code and `CONTRIBUTING.md` moved to sides, role and pool.
