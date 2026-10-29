# Evals

Routing and knowledge regressions for the skills: does "add a flag" load `config-plumbing` *and*
`bindings-update`, does "support model X" go to the Symphony recipe rather than a legacy parser,
does a stale path trigger `/smg:learn`? Each case is a directory with `prompt.md` (the task,
with `max_turns` and `allowed_tools` front matter) and `graders/criteria.md` (an LLM-graded
rubric). They are the format `claude plugin eval` expects.

Run from the repository root (needs the `claude` CLI and API access; each case runs three times
by default and costs real tokens):

```bash
claude plugin eval .                 # every case under evals/
claude plugin eval . --help          # thresholds, single cases, output options
```

Results land in `evals/results/<timestamp>/` (git-ignored). Run them after changing a skill
`description`, the detection table in `skills/implement/SKILL.md`, or a recipe's name; the
scheduled drift workflow does not run them.

Add a case when a lesson shows the guide routed a request wrongly: `claude plugin eval init --bare
<name>` scaffolds the two files.
