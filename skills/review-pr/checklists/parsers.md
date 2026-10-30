# Checklist: parsers (Symphony, legacy) and tokenizer

Symphony (`crates/symphony`, the default):
- [ ] A new table has its `tables!` row in `formats/registry.rs`, module + re-export in `formats/mod.rs`, its groups in `formats/groups.json`, a `Group` row in `tests/readme.rs`, a `Subject` in `tests/parser/contract.rs`, rows in `tests/bellwether_parse_fixtures.rs`, a section in `docs/tables.md`, and the README regenerated (`SYMPHONY_WRITE_README=1 cargo test -p smg-symphony --test readme`).
- [ ] A table that takes a legacy parser name updates `model_gateway/src/routers/grpc/utils/aliases.rs` (`ALIASES` / `UNANSWERED`).
- [ ] Every byte lands in exactly one event; malformed regions come back whole with a `MalformedReason`.

Legacy (`crates/tool_parser`, `crates/reasoning_parser`, for `--parser legacy`):
- [ ] Full trait implemented (incl. `reset`); streaming state correct (buffer, partial token detection, deltas); registered in the `ParserFactory` with model patterns; integration test file under the crate's `tests/`.
- [ ] No legacy parser added for a model Symphony's registry already reads; the thinking-toggle detection in `crates/tokenizer/src/chat_template.rs` updated when a template adds one.

Tokenizer (`crates/tokenizer`):
- [ ] A renderer is picked from `config.json` architectures (`detect_renderer_from_config`) and registered; stop/EOS decoding has tests; `benchmark-tokenizer.yml` still passes.

| Anti-pattern | Consequence | Look for |
|---|---|---|
| Legacy parser for a model Symphony reads | the legacy parser is dead in the default lane | a `tool_parser` / `reasoning_parser` change without a `--parser legacy` reason |
| Table without groups, contract subject or corpus row | unreachable or failing build | `formats/groups.json`, `tests/parser/contract.rs`, `tests/bellwether_parse_fixtures.rs` |
| Bytes dropped without a `DropReason` | text vanishes from the answer | event construction in `crates/symphony/src/engine.rs` |
| Legacy parser state not reset between requests; partial marker prefix lost | stale buffer bleeds; text dropped mid-stream | `reset()` timing; buffer handling on a failed partial match |
