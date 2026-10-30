---
recipe: tokenizer
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/tokenizer/src/
  - crates/tokenizer/tests/
  - model_gateway/src/workflow/tokenizer_registration.rs
  - model_gateway/src/endpoints/tokenize/
  - grpc_servicer/smg_grpc_servicer/tokenizer_bundle.py
exemplars:
  - c030e5d09ffc9186eb6e09c28ad828fde226b2ea   # DeepSeek-V4.1 renderer with its own encoder, picked from config.json, with reference parity fixtures
  - 98f73f7c6f7474eda62c60d7cd270fda8de1c617   # GLM-5.3 text renderer selected by checkpoint metadata plus a template match
  - 9f1c0d907fa241b8f6f85462b24ce8333335ec0e   # factory: a vocab.json + merges.txt checkpoint loads by Hub name and in the fixture harnesses
---

# Add a tokenizer backend or a chat-template renderer

`Tokenizer` (`crates/tokenizer/src/traits.rs`, package `llm-tokenizer`) is `Encoder + Decoder` plus the questions the gateway asks around a render: `apply_chat_template_with_encoding`, `thinking_toggle`, `renderer_capabilities`, `eos_token_ids`.
Two backends implement it, `HuggingFaceTokenizer` (`crates/tokenizer/src/huggingface.rs`) and `TiktokenTokenizer` (`crates/tokenizer/src/tiktoken.rs`); each holds a private `Renderer` enum whose arms are the Jinja template (`ChatTemplateState`, `crates/tokenizer/src/chat_template.rs`) and the native renderers under `crates/tokenizer/src/encoders/`, picked per checkpoint by `detect_renderer_from_config` from `config.json`.
`crates/tokenizer/src/factory.rs` (`create_tokenizer_with_chat_template`, `TokenizerType`) picks the backend from the files in the checkpoint directory; a native renderer states what it answers in a `RendererProfile` table (`crates/tokenizer/src/encoders/mod.rs`).
The gateway builds one tokenizer per worker model in `model_gateway/src/workflow/tokenizer_registration.rs` (`load_tokenizer`: the factory, else the worker's bundle), wraps it in `CachedTokenizer` and owns it in `TokenizerRegistry` under the model name; nothing in the gateway names a backend or a renderer.

Not this recipe:
- a model's output format (tool calls, reasoning blocks): @symphony-format.md
- the registration knobs (`--tokenizer-path`, `--chat-template`, `tokenizer_cache`, `disable_tokenizer_autoload`): @config-plumbing.md
- the processors behind the media parts a renderer only places (`MediaHandling`; `crates/multimodal/src/`): @multimodal-feature.md

## Inputs

| Input | Example | Used in |
|---|---|---|
| Architecture or `model_type` | `DeepseekV41ForCausalLM`, `deepseek_v41` | the `detect_renderer_from_config` arm (step 2) |
| Reference encoder | the checkpoint's `encoding/encoding.py`, or the engine's port of it | the fixture generator and oracle (step 4) |
| Template answers | thinking on by default, key `thinking`, `think_in_prefill` | the `PROFILE` table (step 1) |
| Control tokens | `<｜Assistant｜>`, `<think>` | `marks::control!` in the renderer (step 1) |
| Vocabulary file names | `tiktoken.model`, `*.tiktoken` | the factory branch and both file filters (step 6) |
| Reference ids | `AutoTokenizer` on the same files, `add_special_tokens=False` | the parity test (step 7) |

## Steps

### 1. Write the native renderer beside its family

File: `crates/tokenizer/src/encoders/<family>.rs` — Do: Port the reference encoder as a pure function of the messages and `ChatTemplateParams` (model: `deepseek_v41::encode_messages` and its marked twin `render_messages`; a renderer that only replaces a Jinja template's text returns the `(String, bool)` continuation pair, as `glm53::render` does). Write every control token through `marks::control!` and clean request strings with `marks::without_marks`, so a `</think>` typed in a message stays text. State the answers the gateway asks for in one `pub(crate) const PROFILE: RendererProfile` (each field is documented on the struct). Add `pub mod <family>;` to `crates/tokenizer/src/encoders/mod.rs`.
Verify: `cargo check -p llm-tokenizer` → clean
Trap: `RendererProfile::NO_CAPABILITIES` is a statement, not a default: a renderer that continues a trailing assistant message itself but leaves `native_assistant_continuation` false has the gateway pop that message into a text prefix, which the renderer then writes after its generation header.

### 2. Add the `Renderer` arm and its detection

File: `crates/tokenizer/src/huggingface.rs` — Do: Add the variant to `enum Renderer`, return its table from `Renderer::profile`, dispatch it in `render_marked` (a renderer with its own encoder) or beside `Glm53` in `apply_chat_template` and `apply_chat_template_with_encoding` (a text renderer), and add the arm to `detect_renderer_from_config`: `architectures` first, `model_type` as the fallback, and a revision only the shipped encoder tells apart read from it with a default for the bundle a worker streams, which carries no `encoding/` directory (`detect_dsv41_effort_table`). A tiktoken checkpoint has the same three seams in `crates/tokenizer/src/tiktoken.rs` (`Renderer`, `apply_with_continuation`, `detect_renderer_from_config`); a renderer selected by template match lives in `crates/tokenizer/src/huggingface/glm.rs` (`Checkpoint::load`, `Checkpoint::renderer`) and is re-selected in `set_chat_template`.
Verify: `cargo test -p llm-tokenizer --lib huggingface` → the detection tests pass, yours beside `a_v4_architecture_checkpoint_with_its_own_template_renders_through_it`
Trap: Grouping the new variant with `Jinja | Glm53` in `Renderer::profile` compiles; the gateway then arms its reasoning parser from the template's answers (`should_mark_reasoning_started`, `model_gateway/src/routers/grpc/utils/parsers.rs`) and a prompt that opens `<think>` streams the reasoning as content.

### 3. Prove the checkpoint selects it

File: `crates/tokenizer/tests/render/<family>_renderer.rs` — Do: Write a temp dir holding `MIN_TOKENIZER_JSON_WITH_SENTINELS` (`crates/tokenizer/tests/common/mod.rs`) and a `config.json` naming the architecture, load it with `HuggingFaceTokenizer::from_file`, assert the rendered prompt carries the renderer's header, and add a case with an unrelated architecture that renders through Jinja (model: `crates/tokenizer/tests/render/deepseek_renderer_detection.rs`). Register the module in `crates/tokenizer/tests/render/mod.rs`.
Verify: `cargo test -p llm-tokenizer --test render_tests <family>` → `test result: ok`; with the detection arm commented out the first case fails

### 4. Pin parity with the reference encoder

File: `crates/tokenizer/tests/fixtures/<family>/render_fixtures.json` — Do: Generate the cases by running the reference encoder (generator under `crates/tokenizer/scripts/`, model `generate_deepseek_v41_fixtures.py`; a Python port of the encoder under `crates/tokenizer/scripts/oracle/`), each case naming its oracle and every knob it was rendered with. Deserialize them with `#[serde(deny_unknown_fields)]`, compare the text byte for byte, and the ids against a `render_ids_fixtures.json` recorded with the checkpoint's own tokenizer when the renderer encodes itself (model: `crates/tokenizer/tests/render/deepseek_v41_renderer.rs`, which reads the real tokenizer from an env var or a one-time download under `.tokenizer_cache/`).
Verify: `cargo test -p llm-tokenizer --test render_tests <family>` with the tokenizer directory set → every case compared
Trap: Without the tokenizer the parity test prints a skip notice and passes; run it once with the directory set before calling the port done.

### 5. Implement the backend

File: `crates/tokenizer/src/<backend>.rs` — Do: Implement `Encoder`, `Decoder` and `Tokenizer` from `crates/tokenizer/src/traits.rs` (model: `crates/tokenizer/src/tiktoken.rs`): `encode` returns `Encoding::Plain`, then `decode`, `vocab_size`, `get_special_tokens`, `token_to_id`, `id_to_token`, `as_any`. Hold a `ChatTemplateState` (`ChatTemplateState::from_config`) and answer every template question from it, as `TiktokenTokenizer` does; fill `eos_token_ids` with `load_eos_token_ids` and `with_tokenizer_eos` (`crates/tokenizer/src/eos.rs`); return the raw-pass added tokens from `added_token_strings`. Add `mod <backend>;` and the re-export to `crates/tokenizer/src/lib.rs`.
Verify: `cargo test -p llm-tokenizer --lib <backend>` → `decode(encode(text))` round-trips and `Sequence` yields the same text one id at a time
Trap: Every template method has a default that compiles: an empty `eos_token_ids` means `create_stop_decoder` (`model_gateway/src/routers/grpc/utils/chat_utils.rs`) registers no EOS stop token and Symphony's `stop_texts` knows only the named `eos_token`.

### 6. Teach the factory and the file filters the layout

File: `crates/tokenizer/src/factory.rs` — Do: Add a `TokenizerType` variant and branch `create_tokenizer_with_chat_template` on the directory's file names, after `tokenizer.json` and before the error that lists the accepted layouts, passing the template `resolve_and_log_chat_template` finds; cover the single-file extension arm, `auto_detect_tokenizer` and `get_tokenizer_info`. `create_tokenizer_from_downloaded_dir` hands a Hub checkout to the same loader, but only the names `is_tokenizer_file` (`crates/tokenizer/src/hub.rs`) accepts are downloaded, and a worker's bundle holds only `TOKENIZER_FILES` and `TOKENIZER_GLOBS` (`grpc_servicer/smg_grpc_servicer/tokenizer_bundle.py`): add the new names to both.
Verify: `cargo test -p llm-tokenizer --lib factory` → a temp-dir test of the layout passes (model: `a_downloaded_vocab_and_merges_pair_loads_like_its_tokenizer_json`) and `test_is_tokenizer_file` names the new files
Trap: Tests load a local directory and pass; by Hub name or from a worker bundle the same checkpoint fails only in deployment, with "does not contain a valid tokenizer file", when a filter skipped the vocabulary.

### 7. Prove parity with the reference tokenizer

File: `crates/tokenizer/tests/encode/<backend>_parity.rs` — Do: Compare ids with the reference tokenizer on the same files, opt-in through an env var and `#[ignore]`, printing the first differences (model: `crates/tokenizer/tests/encode/vocab_merges_parity.rs`), and check the special tokens as `tokenizer_config.json` gives them, a `null` meaning none (model: `crates/tokenizer/tests/encode/special_tokens_from_config.rs`). Register the module in `crates/tokenizer/tests/encode/mod.rs`.
Verify: `cargo test -p llm-tokenizer --test encode_tests <backend> -- --ignored` with the env var set → `0 differences`
Trap: `CachedTokenizer` (`crates/tokenizer/src/cache/mod.rs`) splits text at the special tokens `get_special_tokens` returns and never inside the strings `added_token_strings` returns; a backend that reports no special tokens gives the L1 prefix cache no boundary, so every lookup misses (`smg_tokenizer_cache_lookups_total`).

### 8. Confirm the gateway picks it up

File: `model_gateway/src/workflow/tokenizer_registration.rs` — Do: Change nothing; read the path. `load_tokenizer` calls `factory::create_tokenizer_async_with_chat_template` with the source `model_gateway/src/workflow/steps/local/submit_tokenizer_job.rs` took from the worker's `tokenizer_path`, `model_path` or `model_id` label or from the router's `--tokenizer-path` / `--model-path`, falls back to the worker's bundle, wraps the result in `CachedTokenizer` and registers it under the model name. The renderer's answers reach the request path through `renderer_capabilities` and `chat_template_content_format_for_request` (`model_gateway/src/routers/grpc/utils/message_utils.rs`), `thinking_toggle` and `native_thinking_mode` (`model_gateway/src/routers/grpc/utils/parsers.rs`), and a `PromptEncoding::Deferred` job runs in `encode_prompt_blocking` (`model_gateway/src/routers/grpc/utils/chat_utils.rs`).
Verify: `POST /v1/tokenizers` with `{"name": "<model>", "source": "<dir>"}` (`add_tokenizer`, `model_gateway/src/endpoints/tokenize/handlers.rs`), then `POST /v1/tokenize` with `{"model": "<model>", "prompt": "hi"}` → the ids of step 7; `GET /v1/tokenizers` lists the model with its `vocab_size`
Trap: A new `Tokenizer` method with a default body is answered by that default through `CachedTokenizer` and `MockTokenizer` (`crates/tokenizer/src/mock.rs`) until both forward it; the cache is on in production, so the gateway never sees the backend's answer.

### 9. Gate

Run `smg:contribute`.

## Rules

- A renderer's ids are `encode(text, false)` of its text unless it says otherwise: a renderer whose ids are not a function of the text returns `PromptEncoding::Deferred` with an `EncodeJob`, and every wrapper forwards `apply_chat_template_with_encoding`.
- `detect_renderer_from_config` falls back to Jinja on a missing or malformed `config.json` without an error; the V4 arm sends a checkpoint that ships a chat template through the template (`has_chat_template`), as the engine does, so decide that for a new family too.
- `set_chat_template` (an operator's `--chat-template` override) must re-select a template-matched renderer and refresh what was resolved from the template (`media_handling`, `tools_block`).
- `crates/tokenizer/**` changes run the `rust-tokenizer` and `rust-engine` test lanes (`.github/workflows/pr-test-rust.yml`), the bench gate (`.github/workflows/benchmark-tokenizer.yml`, thresholds in `.github/bench-gates/tokenizer.toml`: a slower `encode_throughput` or `decode_performance` group fails the PR) and `.github/workflows/bellwether-fixtures.yml` (`cargo test -p llm-tokenizer --test 'bellwether_*'`, opt-in locally through `BELLWETHER_FIXTURES`).
- `crates/tokenizer/README.md` lists the backends and the native renderers; add the new one.
- Bindings reach a backend through the same factory (`bindings/golang/src/tokenizer.rs` calls `create_tokenizer`); no binding change.
