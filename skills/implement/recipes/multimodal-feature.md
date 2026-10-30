---
recipe: multimodal-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/multimodal/src/
  - crates/multimodal/tests/preprocess/
  - crates/multimodal/scripts/
  - model_gateway/src/routers/grpc/multimodal/
  - crates/engine_zmq_adapter/src/multimodal.rs
exemplars:
  - 8bb7fa65   # Gemma 4: processor + spec for images and video, with a fingerprint golden
  - b19a624f   # Nemotron-H Omni: image, audio and video; capability.rs, plan.rs and process.rs changes
  - 62101268   # Muse Spark: nested processor_config.json sections (config.rs), video frame timestamps (process.rs)
---

# Add a vision model

Media preprocessing lives in crate `llm-multimodal` (lib `llm_multimodal`, dir `crates/multimodal/`). `MediaConnector` (`media.rs`) fetches a `MediaContentPart` into an `Arc<ImageFrame>` / `Arc<VideoClip>`; a `VisionPreProcessor` (`vision/processor.rs`) turns `DynamicImage`s into a `PreprocessedEncoderInputs` bundle (`encoder_inputs.rs`); a `ModelProcessorSpec` (`registry/traits.rs`) chooses placeholder tokens and expands them to `PromptReplacement`s; the tracker (`tracker.rs`) emits `TrackerOutput`. The gateway finds the spec through `ModelRegistry::lookup` (`registry/mod.rs`) and the spec constructs its own processors. Worked pair: `vision/processors/phi3_vision.rs` (`Phi3VisionProcessor`) and `registry/phi3_v.rs` (`Phi3VisionSpec`).

Not this recipe:
- Worker selection, wire assembly and media caches (`model_gateway/src/routers/grpc/multimodal/worker.rs`, `assemble.rs`, `pixel_cache.rs`).
- Audio-only models (`registry/qwen3_asr.rs`, `audio/processor.rs`): same spec contract, `audio_processor()` instead of `vision_processor()`.

## Inputs

| Input | Example | Used in |
|---|---|---|
| Family match | `model_id` substring, or `config.json` `model_type` | 3 (`matches`) |
| Placeholder token / id | `<image>`, `image_token_id` | 3 |
| Modalities and default counts | image 4, video 1 | 3 (`modality_limits`) |
| HF reference processor + config | `image_processing_<model>.py`, `preprocessor_config.json` | 1, 5 |
| Per-item side tensors | `image_sizes`, `image_grid_thw` | 3 (`field_layouts`) |
| Engines that serve it | vLLM, TokenSpeed | 6, 7 |

## Steps

### 1. Implement the processor

File: `crates/multimodal/src/vision/processors/<model>.rs` — Do: implement `VisionPreProcessor`: `default_mean` / `default_std`; `preprocess(&self, images: &[DynamicImage]) -> Result<PreprocessedEncoderInputs, TransformError>` (resize and normalize with `vision/transforms.rs`, then `PreprocessedEncoderInputs::new(encoder_input, feature_token_counts, item_sizes)` — `new` takes any array through `From<Array<f32, D>> for EncoderInput`, so 4D `[B,C,H,W]` and 5D like Phi3's `[B,num_crops+1,C,H,W]` share one constructor; side tensors go in with `.with_extra(key, ModelSpecificValue)`); `calculate_num_tokens(&self, width, height) -> Result<usize, TransformError>`; `model_name`. Take sizes from the HF config the spec hands you (`PreProcessorConfig::get_target_size`, `get_patch_size`), as `Phi3VisionProcessor::with_normalization_of` does. Video needs `preprocess_video` / `preprocess_video_rgb`, whose defaults return `TransformError::ShapeError`.
Verify: `cargo test -p llm-multimodal vision::processors::<model>` → the module's unit tests pass.
Trap: mean, std or patch size hardcoded in `preprocess` compiles, and the model's `preprocessor_config.json` is then ignored without a warning.

### 2. Export the processor

File: `crates/multimodal/src/vision/processors/mod.rs` — Do: add `pub mod <model>;` and `pub use <model>::<Model>Processor;`. There is no processor registry: the spec's `vision_processor()` (or `audio_processor()`) constructs it.
Verify: `cargo check -p llm-multimodal`
Trap: a processor nobody constructs is dead code that compiles — `Phi4VisionProcessor` and `PixtralProcessor` ship with no spec and no prompt-expansion contract.

### 3. Implement the spec

File: `crates/multimodal/src/registry/<model>.rs` — Do: implement `ModelProcessorSpec`: `name`; `matches` on `ModelMetadata { model_id, tokenizer, config }` (`config_model_type()`); `placeholder_token` / `placeholder_token_id` via `metadata.token_id(..)` or `metadata.config_u32(&["image_token_id"])`; `modality_limits`; `vision_processor(model_config, preprocessor_config, modality)`; `prompt_replacements` driven by `preprocessed.feature_token_counts`. For video or audio add the `Modality` to `modality_limits` and override `placeholder_token_for` / `placeholder_token_id_for` / `prompt_replacements_for` (or return `ModalityHooks` from `hooks(modality)`): their defaults answer `ModelRegistryError::UnsupportedModality` for anything but `Image`, and `plan.rs` / `process.rs` call them before expansion (`registry/qwen3_vl.rs` has every piece).

```rust
fn vision_processor(&self, _cfg: &Value, pre: &PreProcessorConfig, modality: Modality)
    -> RegistryResult<Box<dyn VisionPreProcessor>> {
    match modality {
        Modality::Image => Ok(Box::new(<Model>Processor::new().with_normalization_of(pre))),
        _ => Err(ModelRegistryError::UnsupportedModality { spec: self.name(), modality }),
    }
}
fn prompt_replacements(&self, m: &ModelMetadata, p: &PreprocessedEncoderInputs)
    -> RegistryResult<Vec<PromptReplacement>> {
    let (token, id) = (self.placeholder_token(m)?, self.placeholder_token_id(m)?);
    Ok(p.feature_token_counts.iter()
        .map(|&n| PromptReplacement::repeated(Modality::Image, &token, id, n)).collect())
}
```

Verify: `cargo test -p llm-multimodal registry::<model>`
Trap: a hand-counted placeholder count compiles; only `feature_token_counts` matches the tensors the processor emitted.

### 4. Register the spec

File: `crates/multimodal/src/registry/mod.rs` — Do: add `mod <model>;`, `use <model>::<Model>Spec;` and `LazySpec::new(|| Box::new(<Model>Spec))` to the `Vec` in `ModelRegistry::new()`, before any more general spec it could also match (`Qwen3VLVisionSpec` precedes `QwenVLVisionSpec`). `LazySpec::new` takes the factory only — the name comes from `name()`; `lookup` returns the first `matches`.
Verify: `cargo test -p llm-multimodal registry::`
Trap: `mod` + `use` without the `LazySpec` entry compiles; `ModelRegistry::lookup` returns `None` and Step 5's `the_spec_resolves_the_family_and_builds_its_processor` fails.

### 5. Pin preprocessing to the reference with a golden

File: `crates/multimodal/scripts/generate_<model>_preprocess_fingerprints.py`, `crates/multimodal/tests/fixtures/golden/<model>_preprocess_fingerprints.json`, `crates/multimodal/tests/preprocess/<model>_preprocess_golden.rs` — Do: the script runs the HF processor unmodified over seeded images (`make_seeded_image` in `tests/preprocess/mod.rs` regenerates the same pixels) and PNG fixtures, recording sizes, token counts and FNV-1a fingerprints (`fnv1a`, `fnv1a_f32`) of the exact bytes the engine receives; the Rust module reproduces every one, resolving the family through `ModelRegistry::new().lookup(..)`. Register it with `mod <model>_preprocess_golden;` in `crates/multimodal/tests/preprocess/mod.rs`. Model on `gemma4_preprocess_golden.rs` and `generate_gemma4_preprocess_fingerprints.py` (which also pin the reference file's SHA-256, `REFERENCE_SHA256`).
Verify: `cargo test -p llm-multimodal --test preprocess_tests <model>` → `preprocess_matches_the_reference_fingerprints` passes.
Trap: a module file missing from `tests/preprocess/mod.rs` is never compiled, so its test cannot fail.

### 6. Teach the gateway the family

File: `model_gateway/src/routers/grpc/multimodal/{capability,config,plan,process}.rs` — Do: `capability.rs::runtime_supports_modality` is the runtime × modality matrix; `ensure_model_accepts_media` refuses an (engine, modality) pair no worker of the model takes at preparation, before any fetch or decode, and `ensure_backend_supports_modalities` repeats it at worker selection — extend the matrix (and `runtime_reads_format` for a new `EncoderInputFormat`) when the family brings an engine a modality or format it did not have. `config.rs` (`load_image_preprocessor_config`, `load_video_preprocessor_config`) reads `preprocessor_config.json`, the nested `image_processor` / `feature_extractor` sections of `processor_config.json`, and `video_preprocessor_config.json`; `plan.rs` resolves anchors with `placeholder_token_for` (and `rendered_marker_for`); `process.rs` builds processors through `MultimodalModelConfig::vision_processors` and expands with `prompt_replacements_for`.
Verify: `cargo test -p smg routers::grpc::multimodal` → `capability_matrix_matches_backend_support` passes.
Trap: a modality the crate preprocesses but the matrix omits is refused at preparation (`unsupported_modality_message`) with no hint that the spec supports it.

### 7. Worker-side anchor parity (only when the engine expands anchors itself)

File: `crates/multimodal/scripts/check_worker_anchor_parity.py` — Do: a spec returning `true` from `worker_expandable(modality)` (default `false`; `ModalityHooks::worker_expandable`) lets the router send one anchor token per item for a vLLM worker to expand. Add the family to the script's `MODELS` table and run it against vLLM (9c2b7150).
Verify: `python crates/multimodal/scripts/check_worker_anchor_parity.py --model <model>` → the anchor becomes exactly one placeholder range.
Trap: an anchor that is not the single token vLLM's prompt updates target passes every Rust test and corrupts prompts only in worker mode.

### 8. Servicer tokenizer bundle (only when the spec reads a file it does not ship)

File: `grpc_servicer/smg_grpc_servicer/tokenizer_bundle.py` — Do: the gateway reads a worker-served model's tokenizer and processor files from the ZIP the servicer streams; `TOKENIZER_FILES` / `TOKENIZER_GLOBS` list them (631ce06c added `processor_config.json` and `video_preprocessor_config.json`). New tokens for unit tests go into `crates/tokenizer/src/mock.rs` (`with_tokens`).
Verify: `pytest grpc_servicer/tests/test_tokenizer_bundle.py`
Trap: a file missing from the bundle makes the loader fall back silently (`registry_get_or_load_falls_back_when_preprocessor_config_missing`), so the processor runs on its constants.

### 9. Gate

Run `smg:contribute`. Clippy runs `--all-features`, which enables `opencv-video` and needs system OpenCV: `make opencv-deps` (`scripts/install_opencv.sh`) once.

## Rules

- `field_layouts` defaults to `{"pixel_values": Batched}` and any key not listed is shared — replicated to every item (`crates/engine_zmq_adapter/src/multimodal.rs`: `MmField::Batched` indexes row i, `MmFlatField` slices by the sizes tensor, the rest is shared). Declare every per-item side tensor `Batched` (Phi3: `image_sizes`; Qwen3-VL: `image_grid_thw`, `patches_per_image`), keep `FieldLayout::flat("patches_per_image")` for a patchified `pixel_values`, and key the logical `"pixel_values"` even though the field is `encoder_input`. Multi-modality specs override `encoder_field_layouts_for(modality) -> EncoderFieldLayouts` (`qwen3_vl.rs`, `qwen3_omni.rs`, `qwen3_asr.rs`, `inkling.rs`, `nemotron_omni.rs`, `minimax_m3.rs`); the default bridges through `EncoderFieldLayouts::from_legacy_fields`.
- `modality_limits` is a default: `validate_media_request` lets `SMG_IMAGE_MAX_COUNT` / `SMG_VIDEO_MAX_COUNT` / `SMG_AUDIO_MAX_COUNT` raise or lower it but never enables an undeclared modality (`limit_override_does_not_enable_undeclared_modality`).
- Types (`lib.rs` exports): `MediaContentPart` is `Text | ImageUrl | ImageData | ImageEmbeds | AudioUrl | AudioData | VideoUrl | VideoData` (`types.rs`), not `ChatContentPart`; `Modality` is `Image | ImageEmbeds | Audio | Video`; the tracker yields `TrackerOutput`, not `MultiModalInputs`.
- All media flows through `MediaConnector` and `MediaConnectorConfig`: `allowed_domains`; `allowed_local_media_path` gates `MediaSource::File` (else `MediaConnectorError::DisallowedLocalPath`); `fetch_timeout` 10 s, `video_fetch_timeout` 30 s. `fetch_video(.., VideoFetchConfig { min_frames, max_frames, sample_fps, .. })` returns `Arc<VideoClip>`; bytes are Blake3-hashed (`hasher.rs`) for dedup.
- `PreprocessedEncoderInputs` geometry accessors (`channels`, `height`, `width`) error on anything but 4D/5D input; `batch_size` and `total_feature_tokens` always work.
