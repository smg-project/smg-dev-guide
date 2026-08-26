# Adding a Vision Model to SMG

Image preprocessing for vision LLMs lives in the `llm-multimodal` crate (lib `llm_multimodal`, dir `crates/multimodal/`). The `MediaConnector` fetches an image into an `ImageFrame`, a `VisionPreProcessor` turns `DynamicImage`s into a `PreprocessedEncoderInputs` tensor bundle, and a `ModelProcessorSpec` decides placeholder tokens + prompt expansion. Adding a model = a processor + a spec + two registrations.

## Pipeline

```
MediaContentPart (Text | ImageUrl | ImageData | ImageEmbeds | AudioUrl | AudioData | VideoUrl | VideoData)   // types.rs
  -> MediaConnector::fetch_image(MediaSource::{Url,DataUrl,InlineBytes,File}, ImageFetchConfig { detail })  // media.rs, Blake3 hash
  -> Arc<ImageFrame> { image: DynamicImage, raw_bytes, detail, source, hash }
  -> VisionPreProcessor::preprocess(&[DynamicImage], &PreProcessorConfig) -> PreprocessedEncoderInputs
  -> ModelProcessorSpec::prompt_replacements(...) -> Vec<PromptReplacement>  // expands placeholder tokens
  -> tracker emits TrackerOutput { data: MultiModalData, uuids: MultiModalUUIDs }
```

Video is a first-class modality: `MediaConnector::fetch_video(MediaSource::..., VideoFetchConfig { min_frames, max_frames, sample_fps })` returns an `Arc<VideoClip>`, `VisionPreProcessor` has default `preprocess_video` / `preprocess_video_rgb` hooks, and `Modality::Video` flows through the same `PreprocessedEncoderInputs` contract (see `media.rs`, `vision/processor.rs`, `types.rs`).

The worked example below mirrors the existing **Phi3-Vision** pair: `vision/processors/phi3_vision.rs` (`Phi3VisionProcessor`) and `registry/phi3_v.rs` (`Phi3VisionSpec`).

## Steps

### Step 1: Implement the processor

Implement `VisionPreProcessor` (`vision/processor.rs`). `preprocess` returns `PreprocessedEncoderInputs` built with `::new` — a single constructor generic over dimensionality that handles both 4D `[B,C,H,W]` and 5D (e.g. Phi3's `[B,num_crops+1,C,H,W]`) arrays via `into_dyn()` internally — plus `.with_extra(key, ModelSpecificValue)` for model-specific tensors. Reuse `transforms` for resize/normalize.

**File:** `crates/multimodal/src/vision/processors/mymodel.rs`

```rust
use image::DynamicImage;
use crate::vision::{
    processor::{VisionPreProcessor, PreprocessedEncoderInputs},
    preprocessor_config::PreProcessorConfig,
    transforms::TransformError,
};

pub const MYMODEL_MEAN: [f64; 3] = [0.5, 0.5, 0.5];
pub const MYMODEL_STD: [f64; 3] = [0.5, 0.5, 0.5];

#[derive(Debug, Clone, Default)]
pub struct MyModelProcessor;

impl MyModelProcessor {
    pub fn new() -> Self { Self }
}

impl VisionPreProcessor for MyModelProcessor {
    fn default_mean(&self) -> [f64; 3] { MYMODEL_MEAN }
    fn default_std(&self) -> [f64; 3] { MYMODEL_STD }

    fn preprocess(
        &self,
        images: &[DynamicImage],
        config: &PreProcessorConfig,
    ) -> Result<PreprocessedEncoderInputs, TransformError> {
        // resize -> normalize with default_mean()/default_std() -> stack into Array4<f32>
        // feature_token_counts[i] = calculate_num_tokens(w, h, config)
        // item_sizes[i] = (orig_w, orig_h)
        todo!("build encoder_input, then PreprocessedEncoderInputs::new(encoder_input, feature_token_counts, item_sizes)")
    }

    fn calculate_num_tokens(&self, width: u32, height: u32, config: &PreProcessorConfig) -> usize {
        todo!("tokens this image expands to, e.g. (h/patch)*(w/patch)")
    }

    fn model_name(&self) -> &'static str { "mymodel" }
}
```

**Verify:** `cargo test -p llm-multimodal vision::processors::mymodel`

**Anti-pattern:** Hardcoding mean/std/patch_size in `preprocess` instead of reading `config` (`PreProcessorConfig::get_target_size`, `get_patch_size`). The HF preprocessor config must win when present.

### Step 2: Export the processor

**File:** `crates/multimodal/src/vision/processors/mod.rs`

```rust
pub mod mymodel;
pub use mymodel::MyModelProcessor;
```

Then add it to `VisionProcessorRegistry::with_defaults()` in `vision/processor.rs`, registering every lowercase id substring the model uses **plus the HF `config.json` `model_type` string** (e.g. `"phi3_v"`, `"kimi_k3"`). `VisionProcessorRegistry::find(model_id, model_type)` matches case-insensitive `contains` on the id and falls back to `model_type`, so a processor registered only under marketing ids is never found for renamed or custom checkpoints:

```rust
registry.register("mymodel", Box::new(super::processors::MyModelProcessor::new()));
```

**Verify:** `cargo test -p llm-multimodal vision::processor::tests::test_registry_with_defaults`

**Anti-pattern:** Registering a broad pattern (e.g. `"my"`) that also matches another model id. The processor registry is a `HashMap` (iteration order undefined), so use specific, non-overlapping id substrings — registration order does **not** disambiguate here. (Ordering *does* matter for the spec `Vec` registry in Step 4.)

### Step 3: Implement the spec

Implement `ModelProcessorSpec` (`registry/traits.rs`). `matches` is keyed by `ModelMetadata { model_id, tokenizer, config }`; pull token ids from `metadata.token_id(...)` or `metadata.config_u32(&["image_token_id"])`. `prompt_replacements` builds one `PromptReplacement` per image, expanding the placeholder to `feature_token_counts` copies. `modality_limits` is a default, not a hard cap: `validate_media_request` (`registry/traits.rs`) lets a deployment raise or lower it via `SMG_IMAGE_MAX_COUNT` / `SMG_VIDEO_MAX_COUNT` / `SMG_AUDIO_MAX_COUNT`, but an override never enables a modality the spec did not declare.

**File:** `crates/multimodal/src/registry/mymodel.rs`

```rust
use std::collections::HashMap;
use serde_json::{json, Value};
use crate::{
    encoder_inputs::PreprocessedEncoderInputs,
    registry::{ModelMetadata, ModelProcessorSpec, RegistryResult},
    types::{Modality, PromptReplacement, TokenId},
};

pub(super) struct MyModelSpec;

impl ModelProcessorSpec for MyModelSpec {
    fn name(&self) -> &'static str { "mymodel" }

    fn matches(&self, metadata: &ModelMetadata) -> bool {
        let id = metadata.model_id.to_ascii_lowercase();
        id.contains("mymodel")
            || metadata.config_model_type().is_some_and(|mt| mt == "mymodel")
    }

    fn placeholder_token(&self, _metadata: &ModelMetadata) -> RegistryResult<String> {
        Ok("<|image|>".to_owned())
    }

    fn placeholder_token_id(&self, metadata: &ModelMetadata) -> RegistryResult<TokenId> {
        metadata.token_id("<|image|>")
    }

    fn modality_limits(&self, _m: &ModelMetadata) -> RegistryResult<HashMap<Modality, usize>> {
        Ok(HashMap::from([(Modality::Image, 4)]))
    }

    fn processor_kwargs(&self, _m: &ModelMetadata) -> RegistryResult<Value> {
        Ok(json!({}))
    }

    fn prompt_replacements(
        &self,
        metadata: &ModelMetadata,
        preprocessed: &PreprocessedEncoderInputs,
    ) -> RegistryResult<Vec<PromptReplacement>> {
        let token_id = self.placeholder_token_id(metadata)?;
        let token = self.placeholder_token(metadata)?;
        Ok(preprocessed
            .feature_token_counts
            .iter()
            .map(|&count| PromptReplacement::repeated(Modality::Image, &token, token_id, count))
            .collect())
    }
}
```

**Verify:** `cargo test -p llm-multimodal registry::mymodel`

**Anti-pattern:** Hand-counting placeholder tokens. Drive `prompt_replacements` off `preprocessed.feature_token_counts` so the count always matches the tensors the processor emitted.

### Step 4: Register the spec

**File:** `crates/multimodal/src/registry/mod.rs`

Add `mod mymodel;`, `use mymodel::MyModelSpec;`, and a `LazySpec` entry in `ModelRegistry::new()` (order it before any more-general spec it could collide with). `LazySpec::new` takes the factory closure only — the spec name comes from `ModelProcessorSpec::name()`:

```rust
LazySpec::new(|| Box::new(MyModelSpec)),
```

**Verify:** `cargo test -p llm-multimodal`

**Anti-pattern:** Adding the `mod`/`use` but forgetting the `LazySpec` entry, so `ModelRegistry::lookup` never returns the spec.

### Step 5: Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings. Clippy runs `--all-features`, which turns on this crate's `opencv-video` feature and needs system OpenCV — run `make opencv-deps` (`scripts/install_opencv.sh`) once first.

## Critical Rules

- Verify against `crates/multimodal/src/lib.rs` exports: content type is `MediaContentPart` (not `ChatContentPart`); the tracker yields `TrackerOutput`, not any `MultiModalInputs`.
- `field_layouts` defaults to `{"pixel_values": Batched}` and **any key not listed is treated as shared — replicated across every media item** (`registry/traits.rs:ModelProcessorSpec::field_layouts`; `model_gateway/src/routers/grpc/zmq_multimodal.rs`: batched keys index row `i`, flat keys slice by the cumulative sizes tensor, everything else is shared). So declare **every** per-item `model_specific` side tensor as `Batched` (Phi3-Vision: `image_sizes`; Qwen3-VL: `image_grid_thw`, `patches_per_image`), and reserve `FieldLayout::flat("patches_per_image")` for a patchified/flat `pixel_values` (see `qwen3_vl.rs`). The layout key stays the logical `"pixel_values"` HF/vLLM kwarg even though the struct field is `encoder_input`. That map is the legacy shape: multi-modality specs override `encoder_field_layouts_for(modality) -> EncoderFieldLayouts` instead (`registry/qwen3_omni.rs`, `registry/qwen3_asr.rs`, `registry/inkling.rs`), and the trait default bridges via `EncoderFieldLayouts::from_legacy_fields(self.field_layouts())`.
- `PreprocessedEncoderInputs::new` is generic over dimensionality (calls `.into_dyn()`), so the same constructor takes 4D and 5D `encoder_input` arrays; the `channels`/`height`/`width` accessors error on non-4D/5D shapes.
- Registry lookups are substring `contains` (processors) / `matches` (specs). Ordering is load-bearing only for the **spec** registry (`ModelRegistry.specs` is a `Vec`, first `matches` wins — so a specific spec like `Qwen3VLVisionSpec` must precede a general one like `QwenVLVisionSpec`). The **processor** registry is a `HashMap` with unspecified iteration order — there, correctness comes from specific, non-overlapping patterns, not registration order.
- Processor and spec sets are NOT 1:1: `Phi4VisionProcessor` and `PixtralProcessor` exist (`vision/processors/`) with no registered `ModelProcessorSpec`. A processor without a spec preprocesses tensors but has no placeholder/prompt-expansion contract.
- For video, all four pieces are required (see `qwen3_vl.rs`): add `Modality::Video` to `modality_limits`; override `placeholder_token_for` / `placeholder_token_id_for`, whose defaults return `UnsupportedModality` for anything but `Image` and which `model_gateway/src/routers/grpc/multimodal/plan.rs` + `process.rs` call *before* expansion; override the erroring `VisionPreProcessor::preprocess_video` / `preprocess_video_rgb` defaults; emit `Modality::Video` replacements from `prompt_replacements_for`. Miss any one and video requests fail at planning.
- All media flows through `MediaConnector`: honor `MediaConnectorConfig` (`allowed_domains`; `allowed_local_media_path`, which gates `MediaSource::File` — otherwise `MediaConnectorError::DisallowedLocalPath`; `fetch_timeout` default 10s); image, video and audio bytes are Blake3-hashed (`hasher.rs`) for dedup.
