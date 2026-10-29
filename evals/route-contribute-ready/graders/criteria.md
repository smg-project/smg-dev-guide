---
type: llm
weight: 1
---

A successful response uses the smg:contribute skill: it says to run the pre-PR gate (the plugin's scripts/gate.sh, or the equivalent steps: cargo +nightly fmt, clippy with -D warnings, cargo test, pre-commit, the Python lane when config/bindings changed), and it identifies two concrete problems: the branch name my-feature does not match the required <type>/<desc> or <username>/<desc> convention (CI closes such PRs), and the commit lacks a DCO sign-off (git commit -s) — and that the subject 'add thing' is not a conventional commit. It should also mention the PR title convention and the PR body template headers (Description/Problem/Solution/Changes/Test Plan). Fail if it says the PR is ready.
