# Checklist: ZMQ direct backend and engine servicers

- [ ] Wire structs in `crates/engine_zmq_client/src/protocol/` only grow at the tail (`#[serde(default)]` on vLLM, a defaulting `next_element` before `drain_trailing` on TokenSpeed); a round-trip and a short-array test beside them.
- [ ] Translation lives in `crates/engine_zmq_adapter/src/<dialect>.rs`, so the gateway lane and `crates/engine_servicer` both get it; `routers/grpc/zmq_client.rs` only adapts.
- [ ] Every `match` on `ZmqDialect` writes all four arms; no `_ =>`.
- [ ] String stops and EOS stay frontend-side (`stops.rs`, `eos.rs`); nothing sends stop strings over the wire.
- [ ] The e2e lane filter (`e2e_test/fixtures/hooks.py::_filter_zmq_items`) and the CI path filters still select the change; a new dialect has a launcher (`bindings/python/src/smg/serve.py`) and a mock arm in `crates/mock_worker`.

| Anti-pattern | Consequence | Look for |
|---|---|---|
| Field inserted mid-struct | silent wire corruption | `protocol/` struct order changed |
| ZMQ arm on `GrpcClient` | the transport seam leaks | ZMQ code in `routers/grpc/client.rs` |
| Handshake awaited on a request or probe path | the path blocks for the connect timeout | `connect_handshake` outside `spawn_zmq_connect_driver` |
