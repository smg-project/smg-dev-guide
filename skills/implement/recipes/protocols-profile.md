---
recipe: protocols-profile
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/protocols/src/profile/
  - crates/protocols/src/ext/
  - crates/protocols/src/chat.rs
  - crates/protocols/src/validated.rs
  - crates/protocols/tests/protocol/
  - clients/openapi-gen/src/main.rs
exemplars:
  - b5de046e   # the z.ai profile: rules module, variant, model markers, tests
  - e854792c   # the DeepSeek V4 profile with its own integration test file
  - d35d60ca   # a Responses field typed, accepted and kept off the wire (client_metadata)
---

# Add a vendor profile or a protocol field

A profile is the request contract a vendor's acceptance suite enforces on top of the crate's core validation: the `ProviderProfile` enum in `crates/protocols/src/profile/mod.rs` and one rules module per vendor, `crates/protocols/src/profile/zai.rs` being the model to copy.
It is selected from the request's model id by `ProviderProfile::for_model`: a `/`-separated segment that starts with a vendor marker, or a `--model-alias` recorded at startup by `register_model_aliases`, so an alias keeps the profile of the model it serves.
Every Chat Completions request that enters through `ValidatedJson` gets it: `normalize_chat` rewrites the body (vendor defaults, consumed switches, foreign message extensions dropped), then `validate_chat` refuses it with a 400 whose `error.code` is the rule's own code.
The wire types of every API live in this crate too, one file per API; steps 5 and 6 cover changing one.

Not this recipe:
- Proxying to the vendor's hosted API or to an OpenAI-compatible upstream (`crates/external_router`): @provider-api.md.
- The model's tool-call or reasoning markup in its output: @symphony-format.md.
- A new endpoint that carries one of these types (`model_gateway/src/server.rs`, `model_gateway/src/routers/`): @http-endpoint.md.

## Inputs

| Input | Example | Used in |
|---|---|---|
| `<vendor>` | `zai` | `crates/protocols/src/profile/<vendor>.rs`, `mod <vendor>;`, the integration test file name |
| Variant | `ProviderProfile::Zai` | every `match self` in `crates/protocols/src/profile/mod.rs` |
| Model-id markers | `glm`, `zai`, `z-ai` as segment prefixes; exact names as `deepseek::matches_model` | `from_model_segments`; the positive ids and the near misses of `model_id_selects_profile` |
| Contract source | the provider verifier's golden set, then the vendor manual, then live API behaviour | the module doc; one test per rule, named after the verifier's test where one exists |
| Rule codes | `thinking_disabled_not_supported` | `invalid(code, message)`; the `error.code` a client reads and the `error_code` metrics label |
| Field and its spec spelling (step 5) | `client_metadata` on `ResponsesRequest` | the request struct in the API's file and the field's serde attributes |

## Steps

### 1. Write the rules module

File: `crates/protocols/src/profile/<vendor>.rs` — Do: Copy the shape of `crates/protocols/src/profile/zai.rs`: a module doc naming the contract source and what is deliberately not enforced, `const` tables for the pinned values, `pub(super) fn normalize_chat` for defaults the client omitted (`get_or_insert`) and vendor switches the gateway consumes (`req.other.remove`), and `pub(super) fn validate_chat` whose every refusal is `invalid(code, message)` from `crates/protocols/src/common.rs`. A rule that holds for one model generation reads the model through `super::served_under`, as `is_glm53` does, so an opaque alias of a served model keeps it.
Verify: `cargo test -p openai-protocol --lib profile` → the module's `#[cfg(test)]` tests pass, each asserting the refusal by `code`, not by message text.
Trap: a code with whitespace in it (`ValidationError::new("tier must not be gold")`) reaches the client as `invalid_value`; `public_code` in `crates/protocols/src/validated.rs` passes identifier codes through only.

### 2. Add the variant and wire every match

File: `crates/protocols/src/profile/mod.rs` — Do: `mod <vendor>;`, a documented variant on `ProviderProfile`, its marker test in `from_model_segments` (a prefix through `starts_with_ignore_ascii_case`, or exact names as `deepseek::matches_model`), its arm in `normalize_chat` after the foreign-extension pass and in `validate_chat` (with `reject_root` unless the vendor has the `root` role), and the variant in `is_vendor_contract`. The compiler names the remaining matches (`dynamic_tools`, `normalize_chat_for_upstream`). Extend `model_id_selects_profile` with the vendor's ids in every spelling clients send and one near miss that must stay `Generic`.
Verify: `cargo test -p openai-protocol --lib profile::tests` → `model_id_selects_profile` passes with the new ids.
Trap: `is_vendor_contract` is a `matches!` with no exhaustiveness check: left out, it compiles and `register_model_aliases` binds no alias to the profile, so `for_model` of the served model stays `Generic`; the alias test of step 3 is what fails.

### 3. Add the integration test

File: `crates/protocols/tests/protocol/<vendor>_profile.rs`, listed in `crates/protocols/tests/protocol/mod.rs` — Do: Copy the shape of `crates/protocols/tests/protocol/deepseek_profile.rs`: build the request from JSON, call `normalize()` (`openai_protocol::validated::Normalizable`) then `validate()` (`validator::Validate`), and read codes from `field_errors()`, the path every `ValidatedJson` request takes. Add the alias case: `register_model_aliases` with names unique to the test (the table is process-wide), then assert `for_model` of the served model is the variant and that one rule holds under both names.
Verify: `cargo test -p openai-protocol --test protocol_tests <vendor>_profile` → ok; it fails on a skipped `is_vendor_contract` or a missing marker.
Trap: validation runs on the normalized body; a test that calls `validate_chat` without `normalize()` judges a request no client can send (DeepSeek rewrites `minimal` to `low` first).

### 4. Type a message-level vendor field, when the contract enforces one

File: `crates/protocols/src/ext/<vendor>.rs` — Do: Only for a field the contract enforces behaviour on; a cosmetic extra stays in `other`. An all-`Option` struct deriving `Default, PartialEq, Deserialize, Serialize, schemars::JsonSchema` that implements `ProviderExt` with the variant as `PROFILE`, flattened into the `ChatMessage` variant in `crates/protocols/src/chat.rs` beside `KimiSystemExt`; `normalize_chat` then drops it for every other profile through `retain_if` and logs the drop once per request. A struct that exists only so the profile can reject the field gets `#[schemars(skip)]` at the use site. Fields typed onto content parts (`max_long_side_pixel`) are not covered by that pass and are forwarded as sent.
Verify: `cargo test -p openai-protocol --test protocol_tests provider_ext` → ok, with a round trip of your own: the field survives under the vendor's model id and is gone after `normalize()` under `gpt-4o`.

### 5. Add or change a field of a request type

File: the API's file — `crates/protocols/src/chat.rs` (`ChatCompletionRequest`), `completion.rs`, `responses.rs` (`ResponsesRequest`), `messages.rs` (`CreateMessageRequest`, Anthropic), `interactions.rs` (`InteractionsRequest`, Gemini), `decisions.rs`, `systemone.rs`, `realtime_session.rs` — Do: Spell the field as the public spec does, with serde renames where Rust cannot (`#[serde(rename = "type")] pub r#type`, `#[serde(rename_all = "lowercase")]` on enums, `#[serde(tag = "role")]` on `ChatMessage`); make it `Option<T>` or `#[serde(default)]` so an older client and the struct's `Default` keep working (`#[serde(default, deserialize_with = "deserialize_null_as_false")]` for a boolean clients send as `null`); the struct's `#[serde_with::skip_serializing_none]` keeps it off the wire when absent, `#[serde(default, skip_serializing)]` keeps it off the wire always (`client_metadata`). Unknown keys stay in the struct's `#[serde(flatten)] other: Map<String, Value>` where the API has one (chat, Messages); `ResponsesRequest` has `#[serde(deny_unknown_fields)]` instead, so an unknown key there is a 400 `unknown_parameter` until typed. A bound is a `#[validate(...)]` attribute, or a rule in the struct's `#[validate(schema(function = ...))]` function (`validate_chat_cross_parameters`) built with `invalid`; validator's built-in codes are renamed by `public_code`.
Verify: `cargo test -p openai-protocol --test protocol_tests` → ok, with a test that parses the field, asserts `serde_json::to_value` forwards or omits it, and asserts `!request.other.contains_key("<field>")`.
Trap: on a struct with `other`, a misspelled field compiles and the client's key lands in `other`, forwarded raw; only the `other` assertion catches it. Struct literals elsewhere (`build_next_request` in `model_gateway/src/routers/grpc/regular/responses/common.rs`, `model_gateway/tests/api/responses_api_test.rs`) are the compiler's to name.

### 6. Regenerate the client types

File: `clients/openapi-gen/src/main.rs` — Do: The `generate-clients` target of the `Makefile` runs `cargo run -p openapi-gen` over the `schema_for` list in `main.rs`, then `datamodel-codegen` for the Python module (clients/python/smg_client/types/_generated.py) and the Java generator (`clients/java`). Nothing generated is committed (`.gitignore`), so a request type of a new endpoint is added to that list and to the re-exports in `clients/python/smg_client/types/__init__.py`, or no client sees it. CI's `build-wheel` job regenerates the Python types on every PR and `e2e_test/conftest.py` imports them. `grpc-proto-build-check` rebuilds the Python proto package from `crates/grpc_client/proto/`: it concerns a `.proto` change, which a protocol type is not.
Verify: `make generate-openapi` → the written spec (clients/openapi/smg-openapi.yaml, untracked) names the field under its schema; `cd clients/python && pytest -q tests` imports the regenerated module.
Trap: `collect_schema` keys schemas by type name and the last insert wins: a second Rust type with an existing name (`Usage`, `Function`) in another API file replaces the first in every generated client, and nothing fails.

### 7. Gate

Run `smg:contribute`.

## Rules

- A field only one crate writes does not belong in `crates/protocols`: the crate holds the wire types and the rules every entry point shares; gateway-only state rides in the gateway, and a vendor rule that needs the backend at validation time (a pass-through for an upstream proxy) is a router stage, not a profile.
- Profiles are Chat Completions rules; the Responses conversion reaches them only through `unanswerable_tool_result` and the HTTP relay through `normalize_chat_for_upstream`; the Messages API has `crates/protocols/src/messages_validation.rs`.
- What a profile encodes follows the precedence provider verifier > vendor manual > live API behaviour; a documented restriction the vendor's API did not enforce in calibration is left out, as the DeepSeek module doc records.
- `Generic` is the absence of a contract: a self-hosted model passes strict schemas, `json_object` prompts and tool-message pairing to the engine. Only the names `is_openai_vendor_model` lists select `OpenAi`, and an OpenAI-looking alias of a local model binds nothing.
- The 400 envelope is built by `rejection` in `crates/protocols/src/validated.rs`: `type` `invalid_request_error`, `param` the field path (none for a schema-level rule), `code` the rule's, also carried as the `RejectionCode` response extension; `first_violation` reports the first fault in sorted field order, whichever rule ran first.
- `register_model_aliases` runs once, in `AppContext::from_config` (`model_gateway/src/app_context.rs`); every test that registers aliases uses names unique to itself, since the table is shared by every test in the binary.
