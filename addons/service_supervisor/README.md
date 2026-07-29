# `service_supervisor` add-on

An opt-in, source-safe catalog, planner, and lifecycle contract for explicitly
allowlisted local services. The first slice intentionally ships only a
synthetic in-memory adapter: it proves request coalescing, readiness,
dependency ordering, leases, drain, cleanup, and fail-closed policy without
touching Docker, launchd, Ollama, the Docker socket, or any host service.

The shipped runtime has no listener or proxy. A GET/HEAD wake-before-forward
data plane exists only as a hermetic test fixture. The later production front
door remains Caddy plus a metadata-only local-ai wake broker.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_service_supervisor=yes
```

The generated project receives `tools/service_supervisor/`. Read its
`docs/OPERATOR_RUNBOOK.md` before using even the synthetic lifecycle adapter.
