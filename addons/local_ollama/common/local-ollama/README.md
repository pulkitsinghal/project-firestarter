# `local-ollama/` — generic localhost Ollama HTTP client

Transport plumbing for a **local** Ollama server. Pin a model, POST to
`http://{{ ollama_host }}:{{ ollama_port }}` (`/api/generate`, `/api/chat`, or
`/api/embeddings`), decode a typed response, bounded and loopback-first.
No prompts, no domain logic — bring your own on top.

```
local-ollama/
  python/
    local_ollama_client.py   stdlib-only client (urllib)
    selftest.py              offline fake-transport self-test (python3 selftest.py)
  swift/
    LocalOllamaClient.swift            Foundation-only client
    LocalOllamaClientSelfTest.swift    offline mock-transport self-test
```

Full usage, safety posture, and token reference: [`../docs/LOCAL_OLLAMA.md`](../docs/LOCAL_OLLAMA.md).

Quick check (no server needed):

```bash
python3 local-ollama/python/selftest.py
```
