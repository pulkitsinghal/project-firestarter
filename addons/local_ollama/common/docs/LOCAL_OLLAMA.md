# Local Ollama client

A small, generic HTTP client for a **local** [Ollama](https://ollama.com) server
(`ollama serve`). It is transport plumbing only — pin a model, POST a typed JSON
body to one of the three stable endpoints, decode a typed response, bound the
time and size, and turn every failure into a typed error. No prompts, no domain
logic: bring your own on top.

Two variants ship, use whichever your app needs (or both):

| Variant | File | Depends on |
|---------|------|-----------|
| Python  | `local-ollama/python/local_ollama_client.py` | stdlib only (`urllib`) |
| Swift   | `local-ollama/swift/LocalOllamaClient.swift`  | Foundation only |

## Endpoint & defaults

Everything targets `http://{{ ollama_host }}:{{ ollama_port }}` and one of:

- `POST /api/generate` — single-shot completion
- `POST /api/chat` — multi-turn chat
- `POST /api/embeddings` — embed one text

Stamp-time defaults (firestarter tokens — override with `--set`):

| Token | Default | Used for |
|-------|---------|----------|
| `ollama_host` | `{{ ollama_host }}` | server host (loopback) |
| `ollama_port` | `{{ ollama_port }}` | server port |
| `ollama_model` | `{{ ollama_model }}` | `generate` / `chat` |
| `ollama_embed_model` | `{{ ollama_embed_model }}` | `embeddings` |

## Safety posture

- **Loopback-only by default.** A non-loopback host is refused unless you pass
  `allow_nonloopback=True` (Python) / `allowNonLoopback: true` (Swift). A local
  model endpoint should not be pointed at an arbitrary network host by accident.
- **No proxies, no redirects.** The default transport ignores environment
  proxies and never follows a 3xx, so a request can't be silently re-routed.
- **Bounded.** Every call has a timeout and a maximum response size.
- **Content-silent transport.** No cache, cookies, credentials, or logging hook.

This client sends whatever *you* pass it to a local process. It does not read the
screen, the clipboard, files, or any other source — that is your application's
responsibility, and anything sensitive is your app's to keep local.

## Python usage

```python
from local_ollama_client import LocalOllamaClient

client = LocalOllamaClient()                     # loopback defaults from tokens
print(client.generate("Summarize: hello world").response)

reply = client.chat([
    {"role": "system", "content": "You are terse."},
    {"role": "user", "content": "One word for fast?"},
])
print(reply.message.content)

vec = client.embeddings("some text").embedding   # list[float]
```

The request/response handling is unit-testable with **no network** — inject any
object with an `open(request, timeout=...)` method as `opener=`. See
`local-ollama/python/selftest.py` for a complete fake-transport example.

## Swift usage

```swift
let client = try LocalOllamaClient()             // loopback defaults from tokens
let out = try await client.generate(prompt: "Summarize: hello world")
print(out.response)

let reply = try await client.chat(messages: [
    ChatMessage(role: "system", content: "You are terse."),
    ChatMessage(role: "user", content: "One word for fast?"),
])
print(reply.message.content)

let vec = try await client.embeddings(prompt: "some text").embedding  // [Double]
```

Inject a mock conforming to `OllamaTransport` to test with no network — see
`local-ollama/swift/LocalOllamaClientSelfTest.swift`.

## Prerequisites

Install and start Ollama, then pull the pinned model(s):

```bash
ollama serve &                       # listens on {{ ollama_host }}:{{ ollama_port }}
ollama pull {{ ollama_model }}
ollama pull {{ ollama_embed_model }}
```

## Errors

Both variants raise a small typed set: transport failure (server not running),
non-200 HTTP status, non-JSON content type, oversized response, malformed body,
and — before any request — a non-loopback host that wasn't opted into.
