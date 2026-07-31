# `local_ollama` add-on (contributor notes)

> This file documents the add-on for **firestarter maintainers**. It lives above
> `common/`, so the generator does **not** stamp it into projects. The
> user-facing docs are `common/docs/LOCAL_OLLAMA.md` and
> `common/local-ollama/README.md`, which *do* stamp into the project.

## What it is

A **stack-agnostic**, opt-in (default `no`) add-on that ships the *generic
plumbing* for talking to a local `ollama serve` over HTTP — the shape that
consuming projects otherwise hand-roll and duplicate. It is transport only: pin a
model, POST a typed JSON body to `/api/generate` | `/api/chat` |
`/api/embeddings` on `http://{{ ollama_host }}:{{ ollama_port }}`, decode a typed
response, bound the time and size, and raise a typed error for every failure.

**No application logic** is included or referenced — no prompts, no domain
schema, no vision/document/screen handling. That deliberately stays in the
private consumers; only the reusable wire-format plumbing is lifted here.

## Layout (all under `common/`, stamped to `<project>/`)

```
common/local-ollama/python/local_ollama_client.py   stdlib-only client
common/local-ollama/python/selftest.py              offline self-test (no network)
common/local-ollama/swift/LocalOllamaClient.swift   Foundation-only client
common/local-ollama/swift/LocalOllamaClientSelfTest.swift  offline self-test
common/local-ollama/README.md                       stamped quickstart
common/docs/LOCAL_OLLAMA.md                          stamped usage + safety doc
```

## Tokens

Declared in `firestarter.config.json`, substituted as `{{ key }}`:

| Token | Default | Meaning |
|-------|---------|---------|
| `ollama_host` | `127.0.0.1` | server host (loopback) |
| `ollama_port` | `11434` | server port |
| `ollama_model` | `llama3.2` | default `generate`/`chat` model |
| `ollama_embed_model` | `nomic-embed-text` | default `embeddings` model |

The Python source carries these tokens, so the **raw** template file is not valid
Python (e.g. `DEFAULT_PORT = {{ ollama_port }}`) — it only becomes valid after
substitution, exactly like every other `template/` file. Firestarter's own CI
only `py_compile`s `bin/generate.py`, never addon sources, so this is fine; the
*stamped* copy is what `scripts/smoke.sh` compiles in a generated project.

## Design notes

- **Loopback-first.** Both variants refuse a non-loopback host unless the caller
  opts in — a local-model endpoint shouldn't be pointed at the network by accident.
- **No proxy / no redirect.** Python builds an opener with an empty `ProxyHandler`
  and a `redirect_request` that returns `None`; Swift uses an ephemeral
  `URLSession` (no cache/cookies/creds/proxy) and a delegate that cancels
  redirects. A local call can't be silently re-routed.
- **Injectable transport.** Python takes an `opener=`; Swift takes an
  `OllamaTransport`. Both self-tests drive every path with zero network.

## Verify

`python3 addons/local_ollama/common/local-ollama/python/selftest.py` (offline).
Stamp with `--set include_local_ollama=yes` and confirm no `{{` leaks; the
firestarter contract test `tests/test_local_ollama_contract.py` stamps every
stack, runs the stamped self-test, and asserts off-by-default removal.
