# Adding a Reasoning Parser to SMG

Most parsers are thin wrappers around `BaseReasoningParser`, configured with two tokens and an `always_in_reasoning` flag, then registered in the factory by name + model-ID pattern.

## Inputs to gather first

| Input | Example | Notes |
|-------|---------|-------|
| `MODEL_NAME` | `mymodel` | Snake case. Used as file name, struct prefix (`MymodelParser`), factory key, `model_type` |
| Tokens | `<think>` / `</think>` | Start/end delimiters. Confirm against vLLM/SGLang, HF `tokenizer_config.json` (`added_tokens_decoder` / `chat_template`), or model card |
| `always_in_reasoning` | `true` / `false` | `true` if the template injects the start token in the prefill so output begins as reasoning (DeepSeek-R1, MiniMax M2). `false` if output is normal until an explicit start token (Qwen3, GLM-4.5) |
| Patterns | `["my-model", "mymodel-v2"]` | Case-insensitive substrings matched against the model ID. List every variant/alias |

## Steps

### Step 1: Create the parser file

**File:** `crates/reasoning_parser/src/parsers/{MODEL_NAME}.rs`

Model this on `parsers/deepseek_r1.rs`. The `ReasoningParser` trait has SEVEN methods; delegate all to `self.base`. Use `DEFAULT_MAX_BUFFER_SIZE` (4 MB), not a literal.

```rust
use crate::{
    parsers::BaseReasoningParser,
    traits::{ParseError, ParserConfig, ParserResult, ReasoningParser, DEFAULT_MAX_BUFFER_SIZE},
};

pub struct MymodelParser {
    base: BaseReasoningParser,
}

impl MymodelParser {
    pub fn new() -> Self {
        let config = ParserConfig {
            think_start_token: "<think>".to_string(),
            think_end_token: "</think>".to_string(),
            stream_reasoning: true,
            max_buffer_size: DEFAULT_MAX_BUFFER_SIZE,
            always_in_reasoning: false,
        };
        Self {
            base: BaseReasoningParser::new(config).with_model_type("mymodel".to_string()),
        }
    }
}

impl Default for MymodelParser {
    fn default() -> Self {
        Self::new()
    }
}

impl ReasoningParser for MymodelParser {
    fn detect_and_parse_reasoning(&mut self, text: &str) -> Result<ParserResult, ParseError> {
        self.base.detect_and_parse_reasoning(text)
    }

    fn parse_reasoning_streaming_incremental(
        &mut self,
        text: &str,
    ) -> Result<ParserResult, ParseError> {
        self.base.parse_reasoning_streaming_incremental(text)
    }

    fn reset(&mut self) {
        self.base.reset();
    }

    fn model_type(&self) -> &str {
        self.base.model_type()
    }

    fn is_in_reasoning(&self) -> bool {
        self.base.is_in_reasoning()
    }

    fn mark_reasoning_started(&mut self) {
        self.base.mark_reasoning_started();
    }

    fn mark_think_start_stripped(&mut self) {
        self.base.mark_think_start_stripped();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_model_type() {
        let parser = MymodelParser::new();
        assert_eq!(parser.model_type(), "mymodel");
    }

    #[test]
    fn test_reasoning_extraction() {
        let mut parser = MymodelParser::new();
        let result = parser
            .detect_and_parse_reasoning("<think>thinking here</think>normal text")
            .unwrap();
        assert_eq!(result.reasoning_text, "thinking here");
        assert_eq!(result.normal_text, "normal text");
    }
}
```

**Verify:** `cargo check -p reasoning-parser`

**Anti-pattern:** Omitting `mark_reasoning_started` / `mark_think_start_stripped`, or using a non-existent field like `initial_in_reasoning`. Both fail to compile — the trait requires all seven methods and the field is `always_in_reasoning`.

### Step 2: Export the parser

**File:** `crates/reasoning_parser/src/parsers/mod.rs`
```rust
pub mod mymodel;
pub use mymodel::MymodelParser;
```

**File:** `crates/reasoning_parser/src/lib.rs` — add `MymodelParser` to the `pub use parsers::{ ... }` block.

**Verify:** `cargo check -p reasoning-parser`

**Anti-pattern:** Updating only `mod.rs`. The factory imports from the crate root, so a missing `lib.rs` re-export breaks the factory import in Step 3.

### Step 3: Register in the factory

**File:** `crates/reasoning_parser/src/factory.rs` — add `MymodelParser` to the `use crate::parsers::{...}` list, then in `ParserFactory::new()`:

```rust
registry.register_parser("mymodel", || Box::new(MymodelParser::new()));

registry.register_pattern("my-model", "mymodel");
registry.register_pattern("mymodel-v2", "mymodel");
```

Patterns are matched **case-insensitive substring**: `model_id.to_lowercase().contains(pattern)` (factory.rs `create_for_model`; `has_parser_for_model` does the same check without building the parser). First match wins; order more specific patterns before broader ones.

**Verify:** `cargo test -p reasoning-parser`

**Anti-pattern:** A broad pattern (e.g. `"my"`) placed before a more specific one, or registered ahead of an existing family — it shadows the intended parser since the first substring hit wins.

### Step 4: Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

## Critical Rules

- Compose `BaseReasoningParser`; delegate all seven trait methods to `self.base`. It already solves partial tokens, buffer overflow, and start/end stripping.
- For a model whose template injects the start token in the prefill (output starts mid-reasoning), set `always_in_reasoning: true` — that is the entire customization (file-based examples: `parsers/minimax.rs` `MiniMaxParser`, and `parsers/qwen3.rs` `QwenThinkingParser`, factory key `qwen3_thinking`). No `is_first_chunk` field or method overrides.
- `BaseReasoningParser::new` seeds `in_reasoning` from `always_in_reasoning`, and `reset()` restores it — so `is_in_reasoning()` equals the flag on a fresh or reset parser.
- A new model only needs its own file when it has distinct tokens or behavior. Models reusing standard `<think>`/`</think>` can be a config-only `BaseReasoningParser::new(config).with_model_type(...)` registered inline in the factory (see `deepseek_v31`, `kimi_k25`, `kimi_thinking`) — no file in `parsers/`.
- `ParserResult` has exactly two fields: `reasoning_text` and `normal_text`.
- Unknown model IDs fall back to the `passthrough` parser, never an error.
