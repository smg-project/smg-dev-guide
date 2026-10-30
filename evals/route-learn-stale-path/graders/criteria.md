---
type: llm
weight: 1
---

A successful response does two things: it continues the task with the directory (identifying that the provider files and reconciler now live under model_gateway/src/service_discovery/), and it records the discrepancy for the guide using the smg:learn skill — capturing the SMG commit, the exact recipe line, and the evidence, and filing a lesson issue (or a lessons/ entry) rather than silently working around it. It must not suggest editing the installed plugin's skill files in place. Fail if it only answers the SMG question without recording the lesson, or if it tells the user to guess.
