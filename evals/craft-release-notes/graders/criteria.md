---
type: llm
weight: 1
---

A successful response uses the smg:craft skill's release-notes reference (or quotes its rules): the measure is defined in one plain sentence before the table ("the highest request rate each build sustains while time-to-first-token p99 stays under 1 second") and the column header says what is measured with its unit and the versions compared ("Max req/s at TTFT p99 < 1 s (v1.14.0 → v1.15.0)"), not "Capacity at the objective (requests/s)"; it drops the lab words ("objective", "ramps", "step") from the lead or replaces them with plain ones; and it says the release title is "v1.15.0" and nothing else. Fail if it keeps "Capacity at the objective", accepts the title "SMG v1.15.0", or rewrites the lead into another sentence of more than about 30 words.
