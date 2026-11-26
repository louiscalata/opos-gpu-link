# SPDX-License-Identifier: Apache-2.0
"""Read-only discovery for loopback OpenAI-compatible model servers."""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import shutil
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

PROTECTED_PORTS = frozenset({1234, 1236, 8080, 8081, 8765, 8767, 11434, 11435, 4173})
DEFAULT_URLS = ("http://127.0.0.1:1235", "http://127.0.0.1:8000")
TOOLS = ("lms", "llama-server", "ollama")
TIMEOUT = 2
MAX_BODY = 1024 * 1024


def probe_origin(value: str) -> tuple[str, str, int, str]:
    """Validate and normalize the origin without resolving hostnames."""
    url = urlsplit(value)
    if (url.scheme not in ("http", "https") or url.hostname is None
            or url.username is not None or url.password is not None
            or url.query or url.fragment):
        raise ValueError("expected an HTTP(S) loopback URL without credentials, query or fragment")
    host = ipaddress.ip_address("127.0.0.1" if url.hostname == "localhost" else url.hostname)
    if not host.is_loopback or getattr(host, "scope_id", None) is not None:
        raise ValueError("expected a loopback host")
    port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
    if port == 0:
        raise ValueError("expected a nonzero port")
    authority = f"[{host}]" if host.version == 6 else str(host)
    return url.scheme, str(host), port, f"{url.scheme}://{authority}:{port}"


def protected_allowed(url: str, port: int, probe_urls, allow_protected: bool) -> bool:
    return port not in PROTECTED_PORTS or (allow_protected and url in probe_urls)


def backend_kind(server: str, models: list[dict]) -> str:
    header = server.lower()
    if "lm studio" in header or "lm-studio" in header or "lmstudio" in header:
        return "LM Studio"
    if "llama.cpp" in header or "llama-server" in header:
        return "llama.cpp"
    if "vllm" in header or any(model.get("owned_by") == "vllm" for model in models):
        return "vLLM"
    if "ollama" in header or any(model.get("owned_by") == "ollama" for model in models):
        return "Ollama"
    return "OpenAI-compatible"


def _interrupt(transport: socket.socket) -> None:
    try:
        transport.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _probe(scheme: str, host: str, port: int, origin: str) -> dict | None:
    connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
    deadline = time.monotonic() + TIMEOUT
    timer = None
    try:
        connection.sock = socket.create_connection((host, port), TIMEOUT)
        if scheme == "https":
            context = ssl.create_default_context()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            connection.sock.settimeout(remaining)
            connection.sock = context.wrap_socket(connection.sock, server_hostname=host)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        # Keep the total response time bounded even if each read makes progress.
        timer = threading.Timer(remaining, _interrupt, args=(connection.sock,))
        timer.daemon = True
        timer.start()
        connection.request("GET", "/v1/models")
        with connection.getresponse() as response:
            if response.status != 200:
                return None
            body = response.read(MAX_BODY + 1)
            server = response.getheader("Server", "")
        if len(body) > MAX_BODY or time.monotonic() >= deadline:
            return None
        payload = json.loads(body)
        models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(models, list) or not all(
            isinstance(model, dict) and isinstance(model.get("id"), str) and model["id"]
            for model in models
        ):
            return None
        return {"url": origin, "kind": backend_kind(server, models),
                "models": list(dict.fromkeys(model["id"] for model in models))}
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        return None
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def discover(probe_urls=(), allow_protected=False) -> list[dict]:
    """Probe explicit candidates first, then the environment and built-in defaults."""
    probe_urls = tuple(probe_urls)
    backends = []
    seen = set()
    for url in (*probe_urls, os.environ.get("OPENAI_BASE_URL", ""), *DEFAULT_URLS):
        try:
            scheme, host, port, origin = probe_origin(url)
        except ValueError:
            continue
        if origin in seen or not protected_allowed(url, port, probe_urls, allow_protected):
            continue
        seen.add(origin)
        backend = _probe(scheme, host, port, origin)
        if backend is not None:
            backends.append(backend)
    return backends


def print_discovery(probe_urls=(), allow_protected=False, as_json=False) -> None:
    backends = discover(probe_urls, allow_protected)
    paths = {name: shutil.which(name) for name in TOOLS}
    tools = {name: {"present": path is not None, "path": path} for name, path in paths.items()}
    if as_json:
        print(json.dumps({"backends": backends, "tools": tools}))
        return
    for backend in backends:
        models = ", ".join(json.dumps(model) for model in backend["models"]) or "(none)"
        print(f'{backend["url"]} ({backend["kind"]})  {models}')
    if not backends:
        print("No loopback OpenAI-compatible backends found.")
    for name, path in paths.items():
        print(f"{name}: {json.dumps(path) if path is not None else 'not found'}")


def chat_url(base_url: str) -> str:
    """Accept a backend origin, a /v1 base URL, or a full chat route."""
    url = urlsplit(base_url)
    if url.path.rstrip("/") in ("", "/v1") and not url.query:
        return url._replace(path="/v1/chat/completions").geturl()
    return base_url
