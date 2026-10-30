# Checklist: e2e tests and CI lanes

- [ ] Every new e2e test carries `@pytest.mark.engine(...)` and `@pytest.mark.gpu(n)`; a missing `gpu` marker silently lands in the 1-GPU lanes and a missing `engine` marker is deselected from every GPU lane.
- [ ] gRPC-pipeline changes also behave over ZMQ (`e2e-1gpu-chat-zmq` replays single-worker chat) and, for parser changes, under both `E2E_PARSER=symphony` and `legacy`.
- [ ] A new lane is in `detect-changes`' path filters and in the `finish` job's `needs` list of `pr-test-rust.yml`; harness changes pass `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures`.
- [ ] Discovery: `cargo test -p smg --test discovery_tests`; kind lane `SMG_KIND_E2E=1 pytest e2e_test/discovery/kind -m kind`.
- [ ] Every wire feature has a mock arm (`crates/mock_worker`) so the CPU lanes exercise it.
