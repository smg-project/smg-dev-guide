---
type: llm
weight: 1
---

A successful response uses the smg:craft skill (or quotes its vocabulary rule from CONTRIBUTING.md): the disaggregated dispatch has two sides (prefill side, decode side), a worker has a role, the workers of one role are a pool, and 'leg' is not used in code, comments, test names or log lines; it rewrites the first comment with sides. For the second comment it flags 'robust' and 'seamless' as generated-sounding filler and asks what the code actually survives or does. It should mention the vocabulary checker (scripts/check_vocabulary.py) or the gate's vocab row. Fail if it accepts 'leg' or only fixes one of the two comments.
