"""Minimal, keyless NEAR JSON-RPC client (Python standard library only).

Design goals:
- read-only view calls at a fixed block height (archival) or at the latest final block;
- polite to free public endpoints: a shared rate limiter, retries with backoff on 429/5xx;
- deterministic results at a fixed block are cached on disk, so long scans can resume.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://archival-rpc.mainnet.fastnear.com"
FALLBACK_ENDPOINT = "https://archival-rpc.mainnet.near.org"
USER_AGENT = "near-vault-check/0.1 (+https://github.com/lee2017-bit/near-vault-check)"

# Error kinds that are a property of the chain state at that block (safe to cache).
DETERMINISTIC_KINDS = {
    "UNKNOWN_ACCOUNT",
    "CodeDoesNotExist",
    "MethodNotFound",
    "ProhibitedInView",
    "ContractPanic",
    "WasmExecution",
    "UNKNOWN_BLOCK",  # a skipped height never gets a block
}


class ViewError(Exception):
    """A view call that the chain answered with an error (not a transport failure)."""

    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


class TransportError(Exception):
    """The endpoint could not be reached or kept failing after retries."""


def classify_error(err) -> str:
    text = json.dumps(err) if not isinstance(err, str) else err
    for kind in ("UNKNOWN_ACCOUNT", "CodeDoesNotExist", "MethodNotFound", "ProhibitedInView"):
        if kind in text:
            return kind
    if "Smart contract panicked" in text or "panicked" in text:
        return "ContractPanic"
    if "wasm execution failed" in text or "CompilationError" in text:
        return "WasmExecution"
    if "UNKNOWN_BLOCK" in text or "GARBAGE_COLLECTED_BLOCK" in text:
        return "UNKNOWN_BLOCK"
    return "Other"


class RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)


class Client:
    def __init__(
        self,
        endpoint: str | None = None,
        rate: float = 4.0,
        cache_dir: str | None = ".cache/rpc",
        timeout: float = 60.0,
        max_retries: int = 7,
    ):
        self.endpoint = endpoint or os.environ.get("NEAR_RPC", DEFAULT_ENDPOINT)
        self.limiter = RateLimiter(rate)
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.max_retries = max_retries
        self.calls = 0
        self.cache_hits = 0
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    # ---- transport -------------------------------------------------------
    def _post(self, method: str, params) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": "vc", "method": method, "params": params}).encode()
        last = None
        for attempt in range(self.max_retries):
            self.limiter.wait()
            req = urllib.request.Request(
                self.endpoint,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.calls += 1
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                # Some endpoints answer chain-level errors (e.g. UNKNOWN_BLOCK for a skipped
                # height) with HTTP 4xx and a normal JSON-RPC error body: return it as-is.
                try:
                    payload = json.loads(e.read() or b"{}")
                except (ValueError, OSError):
                    payload = {}
                if isinstance(payload, dict) and "error" in payload:
                    self.calls += 1
                    return payload
                if e.code not in (408, 425, 429, 500, 502, 503, 504):
                    raise TransportError(last) from e
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = repr(e)
            time.sleep(min(30.0, 0.5 * 2**attempt) + random.random() * 0.5)
        raise TransportError(f"{method} failed after {self.max_retries} attempts: {last}")

    # ---- cache -----------------------------------------------------------
    def _cache_path(self, key: dict) -> str | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
        return os.path.join(self.cache_dir, digest[:2], digest + ".json")

    def _cache_get(self, key: dict):
        path = self._cache_path(key)
        if path and os.path.exists(path):
            with open(path) as f:
                self.cache_hits += 1
                return json.load(f)
        return None

    def _cache_put(self, key: dict, value) -> None:
        path = self._cache_path(key)
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(value, f)
        os.replace(tmp, path)

    # ---- public API ------------------------------------------------------
    def view(self, account: str, method: str, args: dict | None = None, block: int | None = None):
        """Call a view method. Returns the decoded JSON result or raises ViewError."""
        args = args or {}
        key = {"a": account, "m": method, "args": args, "b": block}
        if block is not None:
            cached = self._cache_get(key)
            if cached is not None:
                if "error" in cached:
                    raise ViewError(cached["error"]["kind"], cached["error"]["message"])
                return cached["ok"]
        params = {
            "request_type": "call_function",
            "account_id": account,
            "method_name": method,
            "args_base64": base64.b64encode(json.dumps(args).encode()).decode(),
        }
        if block is None:
            params["finality"] = "final"
        else:
            params["block_id"] = block
        resp = self._post("query", params)
        err = resp.get("error") or (resp.get("result") or {}).get("error")
        if err:
            kind = classify_error(err)
            message = json.dumps(err)[:300] if not isinstance(err, str) else err[:300]
            if block is not None and kind in DETERMINISTIC_KINDS:
                self._cache_put(key, {"error": {"kind": kind, "message": message}})
            raise ViewError(kind, message)
        raw = bytes(resp["result"]["result"]).decode()
        value = json.loads(raw) if raw else None
        if block is not None:
            self._cache_put(key, {"ok": value})
        return value

    def block_header(self, block: int | None = None) -> dict:
        """Return {height, hash, timestamp_ns} for a block id, or the latest final block."""
        key = {"block_header": block}
        if block is not None:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        params = {"finality": "final"} if block is None else {"block_id": block}
        resp = self._post("block", params)
        if "error" in resp:
            raise ViewError(classify_error(resp["error"]), json.dumps(resp["error"])[:300])
        h = resp["result"]["header"]
        out = {"height": h["height"], "hash": h["hash"], "timestamp_ns": int(h["timestamp_nanosec"])}
        if block is not None:
            self._cache_put(key, out)
        return out
