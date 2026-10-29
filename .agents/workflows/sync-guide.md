---
description: Resync this guide against SMG HEAD (maintainers)
---
1. Read `skills/sync/SKILL.md` and follow its process: measure (`python3 scripts/check_anchors.py --smg <smg checkout>`, `bash scripts/upstream_digest.sh --smg <smg checkout>`, open `lesson` issues), triage, fix, verify (`check_anchors.py` must report 0 broken, `python3 scripts/lint_guide.py` 0 errors), record (`smg-ref.json`, plugin versions), ship (`docs: resync skills with smg HEAD (v<version>)`).
2. Never bump `smg-ref.json` while an anchor is broken.
