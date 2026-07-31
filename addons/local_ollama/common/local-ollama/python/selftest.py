#!/usr/bin/env python3
"""Offline self-test for local_ollama_client (no network, stdlib only).

Injects a fake opener so the request-building, response-parsing, model-pinning,
loopback-guard, and every typed-error path are exercised without a running
`ollama serve`. Run it directly:

    python3 selftest.py

Exits 0 and prints a PASS line on success; raises on any failure. The generated
project's CI ("Tests" job) and firestarter's own contract test both run this.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import local_ollama_client as loc  # noqa: E402


class _Headers:
    def __init__(self, content_type: str = "application/json") -> None:
        self._ct = content_type

    def get(self, name: str, default=None):
        if name.lower() == "content-type":
            return self._ct
        return default


class _FakeResponse:
    def __init__(self, payload, *, status=200, content_type="application/json"):
        if isinstance(payload, (dict, list)):
            self._body = json.dumps(payload).encode("utf-8")
        else:
            self._body = payload
        self.status = status
        self.headers = _Headers(content_type)

    def read(self, amount=None):
        if amount is None:
            return self._body
        return self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Records the last request and returns a canned response (or raises)."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.last_request = None
        self.last_timeout = None

    def open(self, request, timeout=None):
        self.last_request = request
        self.last_timeout = timeout
        if self.error is not None:
            raise self.error
        return self.response

    def sent_body(self):
        return json.loads(self.last_request.data.decode("utf-8"))


def _check(name, condition):
    if not condition:
        raise AssertionError(f"FAIL: {name}")


def main() -> int:
    # -- token defaults are wired ------------------------------------------
    _check("default host is loopback", loc.DEFAULT_HOST in loc.LOOPBACK_HOSTS)
    _check("default port is an int", isinstance(loc.DEFAULT_PORT, int))
    _check("default model non-empty", bool(loc.DEFAULT_MODEL))
    _check("default embed model non-empty", bool(loc.DEFAULT_EMBED_MODEL))

    # -- generate: request shape + typed response --------------------------
    opener = _FakeOpener(_FakeResponse({"model": "m", "response": "hi", "done": True}))
    client = loc.LocalOllamaClient(model="m", opener=opener)
    result = client.generate("say hi", options={"temperature": 0})
    body = opener.sent_body()
    _check("generate hits /api/generate", opener.last_request.full_url.endswith(loc.GENERATE_PATH))
    _check("generate is POST", opener.last_request.get_method() == "POST")
    _check("generate is non-streaming", body["stream"] is False)
    _check("generate pins the model", body["model"] == "m")
    _check("generate forwards options", body["options"] == {"temperature": 0})
    _check("generate content-type header", opener.last_request.get_header("Content-type") == "application/json")
    _check("generate response typed", result.response == "hi" and result.done is True)

    # per-call model override wins over the pinned default
    opener = _FakeOpener(_FakeResponse({"model": "other", "response": "", "done": True}))
    loc.LocalOllamaClient(model="m", opener=opener).generate("x", model="other")
    _check("per-call model override", opener.sent_body()["model"] == "other")

    # -- chat: request shape + typed response ------------------------------
    opener = _FakeOpener(_FakeResponse(
        {"model": "m", "message": {"role": "assistant", "content": "yo"}, "done": True}
    ))
    chat = loc.LocalOllamaClient(model="m", opener=opener).chat(
        [{"role": "user", "content": "hey"}]
    )
    body = opener.sent_body()
    _check("chat hits /api/chat", opener.last_request.full_url.endswith(loc.CHAT_PATH))
    _check("chat forwards messages", body["messages"][0] == {"role": "user", "content": "hey"})
    _check("chat is non-streaming", body["stream"] is False)
    _check("chat response typed", chat.message.role == "assistant" and chat.message.content == "yo")

    # -- embeddings: request shape + typed response ------------------------
    opener = _FakeOpener(_FakeResponse({"model": "e", "embedding": [0.1, 0.2, 0.3]}))
    emb = loc.LocalOllamaClient(embed_model="e", opener=opener).embeddings("text")
    body = opener.sent_body()
    _check("embeddings hits /api/embeddings", opener.last_request.full_url.endswith(loc.EMBEDDINGS_PATH))
    _check("embeddings pins the embed model", body["model"] == "e")
    _check("embeddings response typed", emb.embedding == [0.1, 0.2, 0.3])

    # -- loopback guard ----------------------------------------------------
    try:
        loc.LocalOllamaClient(host="10.0.0.5")
        raise AssertionError("FAIL: non-loopback host should be rejected")
    except loc.EndpointNotAllowedError:
        pass
    # explicit opt-in is honored
    loc.LocalOllamaClient(host="10.0.0.5", allow_nonloopback=True, opener=_FakeOpener())

    # -- error paths -------------------------------------------------------
    err = urllib.error.HTTPError("http://x", 500, "boom", {}, None)
    try:
        loc.LocalOllamaClient(opener=_FakeOpener(error=err)).generate("x")
        raise AssertionError("FAIL: HTTP 500 should raise")
    except loc.HTTPStatusError as exc:
        _check("http status carried", exc.status == 500)

    try:
        loc.LocalOllamaClient(opener=_FakeOpener(error=urllib.error.URLError("refused"))).generate("x")
        raise AssertionError("FAIL: connection failure should raise TransportError")
    except loc.TransportError:
        pass

    try:
        loc.LocalOllamaClient(
            opener=_FakeOpener(_FakeResponse(b"<html>", content_type="text/html"))
        ).generate("x")
        raise AssertionError("FAIL: non-JSON content-type should raise")
    except loc.InvalidResponseError:
        pass

    try:
        loc.LocalOllamaClient(
            opener=_FakeOpener(_FakeResponse(b"not json{", content_type="application/json"))
        ).generate("x")
        raise AssertionError("FAIL: malformed JSON should raise")
    except loc.InvalidResponseError:
        pass

    try:
        loc.LocalOllamaClient(
            max_response_bytes=8,
            opener=_FakeOpener(_FakeResponse({"model": "m", "response": "x" * 100, "done": True})),
        ).generate("x")
        raise AssertionError("FAIL: oversized response should raise")
    except loc.ResponseTooLargeError:
        pass

    print("PASS: local_ollama_client offline self-test (transport, typing, guards, errors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
