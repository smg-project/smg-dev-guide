---
recipe: reasoning-parser
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/reasoning_parser/src/
exemplars:
  - 9d639713   # MiniMax-M3: parser file, factory key + patterns, chat_template.rs thinking_mode toggle, gateway arming
  - 81d43443   # DeepSeek-V4.1: parser file plus the tests/deepseek_v41.rs integration test
  - f22e1067   # Hy4: parser, tests/hy_v4.rs, README row, reasoning_effort toggle
---

# Add a legacy reasoning parser

A parser implements `ReasoningParser` (`crates/reasoning_parser/src/traits.rs`); most compose `BaseReasoningParser` (`parsers/base.rs`) with a `ParserConfig` (two tokens and `always_in_reasoning`) and delegate every method to `self.base`.
It lives in `crates/reasoning_parser/src/parsers/<name>.rs` and is registered in `ParserFactory::new()` (`crates/reasoning_parser/src/factory.rs`) by key and by model-ID pattern.
The gateway builds one per request (`create_reasoning_parser` in `model_gateway/src/routers/grpc/utils/parsers.rs`) and arms it from the chat template's thinking toggle.
A model that reuses plain `<think>` / `</think>` needs no file: register `BaseReasoningParser::new(config).with_model_type(...)` inline in the factory, as `deepseek_v31`, `deepseek_v4`, `kimi_k25` and `kimi_thinking` do.

Not this recipe:
- Legacy lane only. At v1.13.0 the default parser is Symphony (`--parser symphony`, @symphony-format.md): new model support goes into a Symphony format table. Follow this recipe for `--parser legacy`, or for a model outside Symphony's registry that must keep a legacy name (`--tool-call-parser` / `--reasoning-parser`).

## Inputs

| Input | Example | Used in |
|---|---|---|
| Key | `<name>` (file, `with_model_type`, factory key); user-facing as `--reasoning-parser <name>`, the per-model `reasoning_parser` worker label / `ModelCard` override (validated through `registry().has_parser`) and Python `get_available_reasoning_parsers()` | steps 1-3 |
| Tokens | `<think>` / `</think>`; confirm against vLLM/SGLang, HF `tokenizer_config.json` (`added_tokens_decoder` / `chat_template`) or the model card | step 1 |
| `always_in_reasoning` | `true` only when the template has no thinking toggle and output always begins inside reasoning (DeepSeek-R1, MiniMax M2, Step3, Qwen3-Thinking); `false` whenever the template exposes an `enable_thinking` / `thinking` / `thinking_mode` / `reasoning_effort` toggle (Qwen3, GLM-4.5, Kimi-K2.5, Nemotron, DeepSeek-V4), even if it prefills `<think>` | steps 1, 5 |
| Patterns | `["<family>", "<family>-v2"]`: case-insensitive substrings of the model ID; list every alias | step 3 |

## Steps

### 1. Write the parser

File: `crates/reasoning_parser/src/parsers/<name>.rs` — Do: model on `parsers/deepseek_r1.rs`: a struct holding `base: BaseReasoningParser`, built from `ParserConfig { think_start_token, think_end_token, stream_reasoning: true, max_buffer_size: DEFAULT_MAX_BUFFER_SIZE, always_in_reasoning }` and `with_model_type`. Delegate the seven required methods (`detect_and_parse_reasoning`, `parse_reasoning_streaming_incremental`, `reset`, `model_type`, `is_in_reasoning`, `mark_reasoning_started`, `mark_think_start_stripped`) and the defaulted `flush` to `self.base`. Override the other default, `requires_special_tokens()`, to `true` only when the delimiters are tokenizer special tokens (`<|content_thinking|>`, `<|open|>think<|sep|>`); otherwise detokenization strips them before the parser sees them (`parsers/inkling.rs`, `parsers/kimi_k3.rs`). Add `#[cfg(test)]` unit tests for `model_type()` and one extraction.
Verify: `cargo check -p reasoning-parser` → compiles; omitting a required method or using a field such as `initial_in_reasoning` fails here (the field is `always_in_reasoning`).
Trap: `flush()` has an empty default, so a wrapper that does not delegate it compiles but drops the text held at stream end; `crates/reasoning_parser/tests/eof.rs::flush_preserves_partial_markers_for_every_parser` walks every registered key and fails for it.

### 2. Export it

File: `crates/reasoning_parser/src/parsers/mod.rs` — Do: `pub mod <name>;` and `pub use <name>::<Name>Parser;`. File: `crates/reasoning_parser/src/lib.rs` — Do: add `<Name>Parser` to the `pub use parsers::{ ... }` block.
Verify: `cargo check -p reasoning-parser`
Trap: the factory imports from `crate::parsers`, so `mod.rs` alone compiles, but external callers and the integration tests use `reasoning_parser::<Name>Parser`; keep `lib.rs` in sync or the public API drifts.

### 3. Register in the factory

File: `crates/reasoning_parser/src/factory.rs` — Do: import the type; in `ParserFactory::new()` add `registry.register_parser("<name>", || Box::new(<Name>Parser::new()))` and one `registry.register_pattern("<alias>", "<name>")` per alias. Matching is `model_id.to_lowercase().contains(pattern)` in `create_for_model` (`has_parser_for_model` does the same check without building); the first hit wins, so put specific patterns before broad ones and before an existing family that is their substring (`kimi-k3` is registered before `kimi`, `qwen3-thinking` before `qwen3` and `qwen`).
Verify: `cargo test -p reasoning-parser`
Trap: a broad pattern registered ahead of a specific one shadows it silently: the model resolves, to the wrong parser.

### 4. Write the integration test

File: `crates/reasoning_parser/tests/<name>.rs` — Do: one file per parser (`crates/reasoning_parser/tests/deepseek_v41.rs`, `gemma4.rs`, `crates/reasoning_parser/tests/hy_v4.rs`), importing `reasoning_parser::{ParserFactory, ReasoningParser, DEFAULT_MAX_BUFFER_SIZE}` or `reasoning_parser::parsers::<Name>Parser`. Drive `parse_reasoning_streaming_incremental` across every chunk boundary of a sample, after `mark_reasoning_started()` and without it, and end with `flush()`; resolve the factory by a model ID to pin the pattern.
Verify: `cargo test -p reasoning-parser --test <name>`

### 5. Teach the gateway the toggle

File: `crates/tokenizer/src/chat_template.rs` — Do: when the template exposes a thinking switch `detect_thinking_toggle` does not know, return its `ThinkingToggle` (`DefaultOn` / `DefaultOff`) and `ThinkingKeyName` (`EnableThinking`, `Thinking`, `ThinkingMode`, `ReasoningEffort`; 9d639713 added `thinking_mode`, f22e1067 the `reasoning_effort` on/off words). File: `model_gateway/src/routers/grpc/utils/parsers.rs` — Do: read the kwarg in `extract_thinking_from_kwargs`; `should_mark_reasoning_started` arms the parser from the detected toggle.
Verify: `cargo test -p llm-tokenizer chat_template && cargo test -p smg parsers`
Trap: with `always_in_reasoning: false` and an undetected toggle the parser is never armed, so a prefilled `<think>` block streams as content.

### 6. Document

File: `crates/reasoning_parser/README.md` — Do: add a row to the "Supported Models" table (`Model | Token Format | Notes`), as f22e1067 does for Hy4.
Verify: `grep <Name> crates/reasoning_parser/README.md`

### 7. Gate

Run `smg:contribute`.

## Rules

- `BaseReasoningParser` already solves partial tokens, buffer overflow and start/end stripping; use `DEFAULT_MAX_BUFFER_SIZE` (4 MB), never a literal. Multi-channel or typed-block formats that are not a single start/end pair implement `ReasoningParser` directly (`parsers/kimi_k3.rs` `KimiK3Parser`, `parsers/inkling.rs` `InklingParser`), still enforce `DEFAULT_MAX_BUFFER_SIZE` and clear all state in `reset()`.
- `always_in_reasoning: true` is the entire customization for a no-toggle model (`parsers/minimax.rs` `MiniMaxParser`, `parsers/qwen3.rs` `QwenThinkingParser`, key `qwen3_thinking`); there is no `is_first_chunk` field and no method override.
- `BaseReasoningParser::new` seeds `in_reasoning` from `always_in_reasoning` and `reset()` restores it, so `is_in_reasoning()` equals the flag on a fresh or reset parser.
- `ParserResult` has exactly two fields, `reasoning_text` and `normal_text`.
- Unknown model IDs fall back to `passthrough`, never an error.
- A new family lands its tool parser in the same change: `crates/tool_parser/src/parsers/<name>.rs` and a case under `crates/tool_parser/tests/models/` (@tool-parser.md); every recent exemplar did both.
