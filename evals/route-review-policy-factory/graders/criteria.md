---
type: llm
weight: 1
---

A successful review follows the smg:review-pr skill: it maps the files to the config-plumbing and routing sections before giving findings, and it uses the REVIEW.md severity markers (Important, Nit, Pre-existing emoji or words) with file references. It must flag as Important that create_by_name in policies/factory.rs has no arm (a worker policy_hint would silently fall back to the default policy), that ConfigValidator::validate_policy in config/validation.rs needs an arm (non-exhaustive match), and that the CLI and bindings are not updated: the --policy value_parser lists and parse_policy in main.rs, PolicyType and convert_policy in bindings/python/src/lib.rs, policy_from_str in router.py, and COMMON_POLICY_CHOICES in router_args.py. It should ask for tests. Fail if the review approves without the create_by_name finding.
