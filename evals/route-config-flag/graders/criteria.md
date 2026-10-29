---
type: llm
weight: 1
---

A successful response routes through the smg:implement skill and names the config-plumbing recipe together with the bindings-update recipe. It lists model_gateway/src/config/types.rs (field with serde default and the Default impl), a hand-written setter in model_gateway/src/config/builder.rs, the CLI flag in model_gateway/src/main.rs with the builder call in to_router_config, validation in config/validation.rs if the value has invariants, and the Python chain: the Router::new pyo3 signature (appended last), the builder call in bindings/python/src/lib.rs, and a keyword-only RouterArgs field placed in alphabetical order in bindings/python/src/smg/router_args.py (the test_arg_parser.py contract tests). It mentions a *_flows_into_both_configs style test and cargo check/test verification steps. It should not claim a RouterConfig struct literal exists, and it should chain to smg:contribute at the end. Fail if the response writes implementation code without naming the recipe, or if it omits the Python bindings chain.
