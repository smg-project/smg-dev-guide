---
description: Run the SMG pre-PR gate before committing or pushing
---
1. Follow `skills/contribute/SKILL.md`: `bash <smg-dev-guide>/scripts/gate.sh` inside the SMG checkout (or its table of commands by hand); fix every FAIL.
2. Paste the table under the PR's Test Plan; the SKIP rows name the lanes CI will run.
