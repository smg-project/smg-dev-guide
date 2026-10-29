---
type: llm
weight: 1
---

A successful response routes through smg:implement and chooses the symphony-format recipe (crates/symphony) as the primary path, because Symphony is the default parser; it must not propose adding a legacy tool_parser as the main implementation (mentioning the legacy lane as a fallback is fine). It names a new table file under crates/symphony/src/formats/, the tables! registry row in formats/registry.rs, the module and re-export in formats/mod.rs, a checkpoint group line in formats/groups.json, a contract Subject in tests/parser/contract.rs, a corpus row in tests/bellwether_parse_fixtures.rs, and regenerating the README models table with SYMPHONY_WRITE_README=1 cargo test -p smg-symphony --test readme. Fail if the primary plan is crates/tool_parser/src/parsers/acme.rs.
