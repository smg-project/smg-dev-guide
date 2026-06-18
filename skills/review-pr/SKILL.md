---
name: review-pr
description: Use when reviewing a pull request, checking a diff, or doing code review in the SMG repository — enforces systematic subsystem-aware review
---

# SMG PR Review

## The Iron Law

```
NO REVIEW APPROVAL WITHOUT CHECKING ALL TOUCHED SUBSYSTEMS
```

If you haven't mapped the changed files to checklist sections, you cannot start reviewing.

## The Hard Gate

<HARD-GATE>
Do NOT write review comments, approve, or provide feedback until you have:
1. Fetched the full diff
2. Listed every changed file
3. Mapped each file to the checklist sections below
4. Created a task for each applicable section
</HARD-GATE>

## Process

```
1. FETCH: Get the PR diff (gh pr diff <number>)
2. MAP: List changed files → match to sections using the file-to-section table
3. TASK: Create one review task per matched section
4. CHECK: Work through each task, flag issues as blocker/suggestion/nit
5. ANTI-PATTERNS: Read @anti-patterns.md for the touched subsystems
6. SUMMARIZE: List all findings with severity and file:line citations
```

### File-to-Section Mapping

| Files Changed | Review Sections |
|---------------|-----------------|
| `crates/protocols/src/` | 1 (Layering), 3 (Worker Lifecycle) |
| `model_gateway/src/config/` | 2 (Config Plumbing) |
| `model_gateway/src/main.rs` | 2 (Config Plumbing) |
| `model_gateway/src/service_discovery.rs` | 3 (Worker Lifecycle) |
| `model_gateway/src/worker/`, `model_gateway/src/workflow/steps/local/` | 3 (Worker Lifecycle) |
| `model_gateway/src/policies/` | 4 (Routing Policy) |
| `model_gateway/src/routers/` (incl. `anthropic/`, `gemini/`, `responses/`, `conversations/`, `grpc/`) | 1 (Layering), 4 (Routing Policy) |
| `model_gateway/src/middleware/` (scheduler, tenant_resolution, rate limit) | 1 (Layering), 10 (Architecture) — no dedicated section yet |
| `crates/tool_parser/src/` | 5 (Parser Changes) |
| `crates/reasoning_parser/src/` | 5 (Parser Changes) |
| `crates/data_connector/src/` | 6 (Storage) |
| `bindings/` | 2 (Config Plumbing) |
| Any file | 7 (Error Handling), 8 (Testing), 9 (Code Quality) |

Sections 7, 8, 9 always apply. Section 10 applies to PRs touching 3+ files or adding new types.

## Review Checklist

### 1. Layering & Separation of Concerns

- [ ] No new fields in `crates/protocols/` types that only one crate sets
- [ ] Config types at correct layer: user-facing → `config/types.rs`, runtime → module-specific
- [ ] No raw strings parsed at runtime — parse at boundary
- [ ] WASM/MCP concerns stay in their crates, not leaking into core

### 2. Config Plumbing

- [ ] BOTH `to_router_config()` AND `to_server_config()` in main.rs updated
- [ ] CLI flag has `value_parser` validation
- [ ] `Default` impl includes new fields
- [ ] `#[serde(default, skip_serializing_if)]` for backward compat
- [ ] Python bindings struct literals updated
- [ ] Go SDK updated if new types exposed

### 3. Worker Lifecycle & Label Pipeline

- [ ] New metadata flows through label pipeline (not parallel `_override` fields)
- [ ] Model ID resolution chain not bypassed
- [ ] WorkerSpec kept minimal at discovery time
- [ ] No post-hoc ModelCard mutation — inject via labels before `build_model_card`

### 4. Routing Policy

- [ ] Works for both HTTP and gRPC paths (`SelectWorkerInfo`)
- [ ] All state is `Send + Sync` (DashMap, Arc — no bare Mutex on hot paths)
- [ ] No `.unwrap()` on worker slices — handle empty list
- [ ] Circuit breaker checked: `w.is_healthy() && w.circuit_breaker_can_execute()`
- [ ] Policy implements `LoadBalancingPolicy` and is registered in `policies/factory.rs` with a `PolicyConfig` enum variant

### 5. Parser Changes (Tool / Reasoning)

- [ ] Implements full trait (all methods + `reset`)
- [ ] Streaming state correct (buffer, partial token detection, delta calc)
- [ ] Registered in `ParserFactory` with model pattern mapping
- [ ] Tests: single call, multiple calls, streaming at boundaries, invalid input

### 6. Storage / Data Connector

- [ ] Implements all required traits
- [ ] Schema migrations handled
- [ ] Hook system integration (audit, validation)
- [ ] Batch operations supported

### 7. Error Handling

- [ ] No `unwrap()` in production code
- [ ] Meaningful error messages with `anyhow::Context`
- [ ] Invalid config fails loudly — no silent fallback to None
- [ ] `thiserror` for domain errors, `anyhow` for wrapping

### 8. Testing

- [ ] Unit tests for new types/parsing including error cases
- [ ] Integration test for full flow
- [ ] Existing test struct literals updated with new fields
- [ ] E2E tests if user-facing behavior changes (in `e2e_test/` — tests run sequentially with class-scoped backends)
- [ ] E2E test markers set: `@pytest.mark.engine(...)`, `@pytest.mark.gpu(count)`, `@pytest.mark.model(...)` as needed

### 9. Code Quality

- [ ] Conventional commit format
- [ ] DCO sign-off present
- [ ] No AI attribution
- [ ] `cargo +nightly fmt --all` clean
- [ ] `cargo clippy --all-targets --all-features -- -D warnings` clean
- [ ] Uses `#[expect]` with reason, not `#[allow]`
- [ ] `tracing` for logging, not `println!`

### 10. Architecture Smell Tests

- "If I remove K8s, does this change still make sense?" → shouldn't be in `crates/protocols/`
- "Can existing config overrides or labels achieve this?" → may be unnecessary
- "Does this compose with DP-aware mode, PD disagg, mesh HA?" → don't break existing
- "Is this Send + Sync safe under concurrent load?" → all routing state thread-safe
- "Did I check both HTTP and gRPC paths?" → dual-mode is easy to forget

See @anti-patterns.md for subsystem-specific anti-patterns.

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "This change is small, I can eyeball it" | Small changes cause the biggest bugs — the two-path config rule is a one-line omission. |
| "I know this code well" | Familiarity breeds blindness. Use the checklist. |
| "It's just a config change" | Config changes touch the most layers (CLI → types → main.rs → bindings). Check section 2. |
| "Tests pass so it's fine" | Tests don't catch layering violations, missing bindings, or one-path config bugs. |

## Red Flags — STOP

- About to approve without mapping files to sections
- Skipping a section because "it doesn't apply" without checking the mapping table
- No file:line citations in review comments
- Approving a config change without verifying both conversion paths
- Reviewing without fetching the actual diff first
