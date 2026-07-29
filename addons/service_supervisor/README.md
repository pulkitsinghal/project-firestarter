# `service_supervisor` add-on

An opt-in, source-safe catalog, planner, lifecycle contract, and PM
execution-permit verifier for explicitly allowlisted local services. The
lifecycle runtime intentionally ships only a synthetic in-memory adapter. The
0.2 verifier can validate typed local-ai dry-run plans/results and consume an
exact signed permit, but it can only produce a separately authenticated,
short-lived handoff receipt for a future broker/executor. Nothing here executes
the plan or touches Docker, launchd, Ollama,
the Docker socket, a network endpoint, or any host service.

The shipped runtime has no listener or proxy. A GET/HEAD wake-before-forward
data plane exists only as a hermetic test fixture. The later production front
door remains Caddy plus a metadata-only local-ai wake broker.

Enable it while stamping:

```bash
./bin/firestart.sh --defaults --set include_service_supervisor=yes
```

The generated project receives `tools/service_supervisor/`. Read its
`docs/OPERATOR_RUNBOOK.md` before using even the synthetic lifecycle adapter.
