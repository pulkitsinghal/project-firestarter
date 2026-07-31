"""Generic localhost Ollama HTTP client (stdlib only, no pip).

This is the *transport plumbing* for talking to a local `ollama serve` over HTTP:
pin a model, POST a typed JSON body to one of the three stable endpoints
(`/api/generate`, `/api/chat`, `/api/embeddings`) on
http://{{ ollama_host }}:{{ ollama_port }}, parse a typed response, bound the
time and the response size, and turn every failure mode into a typed error.

It carries **no** application logic — no prompts, no domain schema, no vision or
document handling. Wire your own prompts/messages on top; keep this file as the
one place the wire format and its gotchas live.

Defaults come from firestarter tokens so a `--set ollama_model=...` at stamp time
bakes straight in:
  * host  = {{ ollama_host }}
  * port  = {{ ollama_port }}
  * model = {{ ollama_model }}          (generate / chat)
  * embed = {{ ollama_embed_model }}    (embeddings)

Safety posture (why this stays boring on purpose):
  * **Loopback-only by default.** The client refuses a non-loopback host unless
    you pass ``allow_nonloopback=True`` — a local model endpoint should not be
    pointed at an arbitrary network host by accident.
  * **No proxies, no redirects.** The default opener ignores environment proxies
    and never follows a 3xx, so a request can't be silently re-routed.
  * **Bounded.** Every call has a timeout and a maximum response size.

Injectable transport: pass any object with an ``open(request, timeout=...)``
method (the urllib ``OpenerDirector`` shape) as ``opener=`` to unit-test the
request/response handling with zero network — see ``selftest.py``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence

# --- Tokenized defaults ------------------------------------------------------

DEFAULT_HOST: str = "{{ ollama_host }}"
DEFAULT_PORT: int = {{ ollama_port }}
DEFAULT_MODEL: str = "{{ ollama_model }}"
DEFAULT_EMBED_MODEL: str = "{{ ollama_embed_model }}"

DEFAULT_TIMEOUT: float = 180.0
DEFAULT_MAX_RESPONSE_BYTES: int = 16 * 1024 * 1024

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

GENERATE_PATH = "/api/generate"
CHAT_PATH = "/api/chat"
EMBEDDINGS_PATH = "/api/embeddings"


# --- Errors ------------------------------------------------------------------

class LocalOllamaError(Exception):
    """Base class for every error this client raises."""


class EndpointNotAllowedError(LocalOllamaError):
    """The configured host is not loopback and non-loopback was not opted in."""


class TransportError(LocalOllamaError):
    """The request never produced an HTTP response (connection refused, DNS,
    timeout, TLS, …). Usually means `ollama serve` isn't running."""


class HTTPStatusError(LocalOllamaError):
    """The server answered with a non-200 status."""

    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self.body = body
        super().__init__(f"ollama returned HTTP {status}")


class InvalidResponseError(LocalOllamaError):
    """The response was not the JSON object shape this client expects."""


class ResponseTooLargeError(LocalOllamaError):
    """The response exceeded ``max_response_bytes``."""


# --- Typed responses ---------------------------------------------------------

@dataclass(frozen=True)
class GenerateResponse:
    model: str
    response: str
    done: bool
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatResponse:
    model: str
    message: ChatMessage
    done: bool
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class EmbeddingsResponse:
    model: str
    embedding: Sequence[float]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


# --- Transport ---------------------------------------------------------------

class _Opener(Protocol):
    def open(self, request: urllib.request.Request, timeout: float): ...  # noqa: E704


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: a local model call must not be re-routed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _default_opener() -> urllib.request.OpenerDirector:
    # Empty ProxyHandler => ignore HTTP(S)_PROXY env vars for loopback calls.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


# --- Client ------------------------------------------------------------------

class LocalOllamaClient:
    """Typed, bounded, loopback-first HTTP client for a local Ollama server."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        model: str = DEFAULT_MODEL,
        embed_model: str = DEFAULT_EMBED_MODEL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        allow_nonloopback: bool = False,
        opener: Optional[_Opener] = None,
    ) -> None:
        if not allow_nonloopback and host not in LOOPBACK_HOSTS:
            raise EndpointNotAllowedError(
                f"host {host!r} is not loopback; pass allow_nonloopback=True to override"
            )
        self.host = host
        self.port = int(port)
        self.model = model
        self.embed_model = embed_model
        self.timeout = float(timeout)
        self.max_response_bytes = int(max_response_bytes)
        self._opener = opener if opener is not None else _default_opener()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # -- public API --

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        options: Optional[Mapping[str, Any]] = None,
        keep_alive: Optional[str] = "5m",
    ) -> GenerateResponse:
        """Single-shot completion via ``/api/generate`` (non-streaming)."""
        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system is not None:
            payload["system"] = system
        if options:
            payload["options"] = dict(options)
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        data = self._post(GENERATE_PATH, payload)
        return GenerateResponse(
            model=str(data.get("model", "")),
            response=str(data.get("response", "")),
            done=bool(data.get("done", False)),
            raw=data,
        )

    def chat(
        self,
        messages: Iterable[Mapping[str, str]],
        *,
        model: Optional[str] = None,
        options: Optional[Mapping[str, Any]] = None,
        keep_alive: Optional[str] = "5m",
    ) -> ChatResponse:
        """Multi-turn chat via ``/api/chat`` (non-streaming). ``messages`` is a
        list of ``{"role": ..., "content": ...}`` mappings."""
        msgs = [{"role": str(m["role"]), "content": str(m["content"])} for m in messages]
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": msgs,
            "stream": False,
        }
        if options:
            payload["options"] = dict(options)
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        data = self._post(CHAT_PATH, payload)
        raw_message = data.get("message") or {}
        message = ChatMessage(
            role=str(raw_message.get("role", "")),
            content=str(raw_message.get("content", "")),
        )
        return ChatResponse(
            model=str(data.get("model", "")),
            message=message,
            done=bool(data.get("done", False)),
            raw=data,
        )

    def embeddings(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        keep_alive: Optional[str] = "5m",
    ) -> EmbeddingsResponse:
        """Embed one text via ``/api/embeddings``."""
        payload: dict[str, Any] = {
            "model": model or self.embed_model,
            "prompt": prompt,
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        data = self._post(EMBEDDINGS_PATH, payload)
        vector = data.get("embedding", [])
        if not isinstance(vector, list):
            raise InvalidResponseError("`embedding` was not a list")
        try:
            embedding = [float(x) for x in vector]
        except (TypeError, ValueError) as exc:
            raise InvalidResponseError("`embedding` held a non-numeric value") from exc
        return EmbeddingsResponse(
            model=str(data.get("model", "")),
            embedding=embedding,
            raw=data,
        )

    # -- transport --

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")

        try:
            response = self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:  # 4xx/5xx (and blocked 3xx)
            detail = ""
            try:
                detail = exc.read(2048).decode("utf-8", "replace")
            except Exception:  # pragma: no cover - best-effort detail only
                pass
            raise HTTPStatusError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise TransportError(str(exc.reason)) from exc
        except (TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc

        with response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status != 200:
                raise HTTPStatusError(int(status))
            content_type = (response.headers.get("Content-Type") or "").lower()
            if not content_type.startswith("application/json"):
                raise InvalidResponseError(f"unexpected content-type: {content_type!r}")
            raw = response.read(self.max_response_bytes + 1)

        if len(raw) > self.max_response_bytes:
            raise ResponseTooLargeError(
                f"response exceeded {self.max_response_bytes} bytes"
            )
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidResponseError("response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise InvalidResponseError("response was not a JSON object")
        return data


__all__ = [
    "LocalOllamaClient",
    "GenerateResponse",
    "ChatResponse",
    "ChatMessage",
    "EmbeddingsResponse",
    "LocalOllamaError",
    "EndpointNotAllowedError",
    "TransportError",
    "HTTPStatusError",
    "InvalidResponseError",
    "ResponseTooLargeError",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_MODEL",
    "DEFAULT_EMBED_MODEL",
]
