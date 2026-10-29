---
description: Run the SMG pre-PR quality gate before committing or pushing
---
1. Read `skills/contribute/SKILL.md`.
2. From inside the SMG checkout run `bash <smg-dev-guide>/scripts/gate.sh` (add `--fix` to let rustfmt/ruff rewrite files). Without the script, run the commands from the skill's table in the same order.
3. Fix every FAIL row and re-run until the table reports PASS. SKIP rows name tools you lack; mention them in the PR so reviewers know CI will cover them.
4. Check the commit, branch and PR rules in the skill (DCO sign-off, no AI attribution trailers, `<type>/<desc>` branch, conventional PR title, the PR body template headers).
