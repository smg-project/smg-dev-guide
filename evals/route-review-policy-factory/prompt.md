---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
---

Review this change to smg-project/smg: the diff adds a PolicyConfig::WeightedRandom variant with a serde rename in model_gateway/src/config/types.rs, a new model_gateway/src/policies/weighted_random.rs implementing LoadBalancingPolicy, a mod/pub use line in policies/mod.rs, and a PolicyConfig::WeightedRandom => Arc::new(WeightedRandomPolicy::new()) arm in create_from_config in policies/factory.rs. Nothing else changed. Without running anything, write the review you would post.
