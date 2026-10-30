---
type: llm
weight: 1
---

A successful response uses the smg:map skill (or clearly draws on it) and explains that Symphony (crates/symphony) is the default parser whose registry (formats/registry.rs with formats/groups.json, lookup by model name) picks a format table per model; that --parser accepts symphony (default) or legacy, where legacy selects the per-model crates/tool_parser and crates/reasoning_parser; and that a model outside Symphony's registry can be read with a table named through worker labels or --tool-call-parser / --reasoning-parser, otherwise falling back to the legacy parsers. Fail if the answer describes tool_parser/reasoning_parser as the default path with no mention of Symphony.
