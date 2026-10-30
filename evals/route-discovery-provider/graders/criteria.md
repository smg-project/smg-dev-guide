---
type: llm
weight: 1
---

A successful response routes through smg:implement to the discovery-provider recipe (not discovery-feature, which is for a label flowing through the pipeline). It names a new provider file under model_gateway/src/service_discovery/, a DiscoveryKind variant, the RuntimeDiscoveryConfig::from_config arm in runtime.rs, the DiscoveryConfig variant and validation arm in config/, DiscoveryArgs flags in main.rs with a guard so that flags alone do not silently start the gateway without discovery, recorded fixtures under service_discovery/testdata/, the launcher mapping in bindings/python/src/smg/router.py and router_args.py with the parity and startup tests, an integration test under model_gateway/tests/discovery/, an e2e package under e2e_test/discovery/ with a job in e2e-discovery.yml, and the Helm chart values. It should mention the exemplar commits for Consul/Slurm/file as the shape to copy. Fail if it proposes editing the reconciler for provider-specific logic.
