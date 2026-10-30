---
type: llm
weight: 1
---

A successful response routes through smg:implement to the http-endpoint recipe (not provider-api, which is for forwarding to third-party providers). It names the request type in crates/protocols, the RouterTrait default method in model_gateway/src/routers/mod.rs, the handler and route in server.rs, dispatch in routers/gateway.rs, the HTTP router implementation, the gRPC pipeline side (an Endpoint variant, stages, execute_<endpoint>), the ENDPOINT_* metrics label and path map, an integration test under model_gateway/tests/http/, and an e2e test under e2e_test/router/ that must be named in a lane. Fail if it treats the task as a config flag or as an external provider router.
