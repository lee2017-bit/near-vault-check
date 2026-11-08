"""Maintainer-only: re-download every committed snapshot from public RPC.

Nothing here is needed to reproduce the results: `python -m vaultcheck reproduce`
works offline from data/. This module documents exactly how data/ was produced.
"""

from __future__ import annotations

import datetime as dt
import json
import os

from .rpc import Client, ViewError
from .scan import pair, scan
from .tokens import INTENTS, fetch_metadata, fetch_token_api, fungible_universe

# The incident token: USDT on BNB Chain, bridged through HOT Omni (NEP-245, 18 decimals).
INCIDENT_TOKEN = "nep245:v2_1.omni.hot.tg:56_2CMMyVTGZkeyNZTSvS5sarzfir6g"

# Window around the published incident (2026-09-29 16:14 to 2026-10-02 20:38 UTC).
WINDOW_START = 217_500_000  # 2026-09-27
WINDOW_END = 218_400_000  # 2026-10-03
DENSE_START = 217_700_000
DENSE_END = 218_300_000
DENSE_STEP = 1_000  # ~17 minutes at ~1 block/s
GRID_STEP = 50_000  # full 717-token scans, ~14 h apart
GAP_THRESHOLDS_RAW = [1, 10**21, 10**22, 10**23, 10**24, 10**25, 10**26]  # 18-decimals: >0, 1k, 10k, 100k, 1M, 10M, 100M


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def collect_universe(client: Client, data: str) -> list[str]:
    head = client.block_header()
    ids = fungible_universe(client, head["height"])
    _write(f"{data}/universe.json", {"block_height": head["height"], "collected_at": _now(), "contract": INTENTS, "token_ids": ids})
    log(f"universe: {len(ids)} fungible ids at {head['height']}")
    return ids


def collect_metadata(client: Client, data: str, ids: list[str]) -> None:
    meta = fetch_metadata(client, ids, None)
    _write(f"{data}/token_meta.json", {"collected_at": _now(), "tokens": meta})
    try:
        api = fetch_token_api()
        _write(f"{data}/token_api.json", {"collected_at": _now(), "source": "https://api-mng-console.chaindefuser.com/api/tokens", "items": api})
    except Exception as e:  # optional enrichment (prices)
        log(f"token api unavailable: {e}")
    log("metadata done")


def existing_block(client: Client, height: int, tries: int = 20) -> int:
    """NEAR skips some heights; return the first height >= `height` that has a block."""
    for h in range(height, height + tries):
        try:
            return client.block_header(h)["height"]
        except ViewError:
            continue
    raise ViewError("UNKNOWN_BLOCK", f"no block in [{height}, {height + tries})")


def collect_scans(client: Client, data: str, ids: list[str], blocks: list[int | None]) -> None:
    for b in blocks:
        if b is not None:
            b = existing_block(client, b)
        snap = scan(client, ids, b)
        _write(f"{data}/scans/{snap['block_height']}.json", snap)
        bad = sum(1 for r in snap["rows"] if r["vault"] is None or r["ledger"] is None)
        log(f"scan {snap['block_height']}: {len(snap['rows'])} rows, {bad} unverifiable, {snap['seconds']}")


def repair_scans(client: Client, data: str) -> None:
    """Re-read rows whose error was transient (not a fact about the chain) in saved scans."""
    import glob

    from .rpc import DETERMINISTIC_KINDS
    from .scan import read_vault

    for path in sorted(glob.glob(f"{data}/scans/*.json")):
        with open(path) as f:
            snap = json.load(f)
        todo = [r["token"] for r in snap["rows"] if r.get("error") and r["error"] not in DETERMINISTIC_KINDS]
        if not todo:
            continue
        values, errors = read_vault(client, todo, snap["block_height"], workers=2)
        fixed = 0
        for r in snap["rows"]:
            if r["token"] in values:
                r["vault"] = values[r["token"]]
                if r["token"] in errors:
                    r["error"] = errors[r["token"]]
                else:
                    r.pop("error", None)
                    fixed += 1
        _write(path, snap)
        log(f"repair {snap['block_height']}: {fixed}/{len(todo)} transient errors resolved")


def _gap(row: dict) -> int:
    return int(row["ledger"]) - int(row["vault"])


def bisect_first(probe, pred, lo: int, hi: int) -> int:
    """Smallest existing block height h in (lo, hi] with pred(probe(h)) true.

    Requires pred false at lo and true at hi. NEAR skips some heights; a skipped
    midpoint is replaced by the nearest existing height strictly inside (lo, hi),
    so the search never jumps past the real transition.
    """
    while hi - lo > 1:
        mid = (lo + hi) // 2
        h = r = None
        for d in range(hi - lo):
            for cand in (mid - d, mid + d):
                if lo < cand < hi:
                    try:
                        r = probe(cand)
                        h = cand
                        break
                    except ViewError:
                        continue
            if h is not None:
                break
        if h is None:  # no block strictly between lo and hi
            return hi
        if pred(r):
            hi = h
        else:
            lo = h
    return hi


def collect_series(client: Client, data: str, token: str = INCIDENT_TOKEN) -> None:
    """Dense per-block series for one token, then exact first-crossing blocks by bisection."""
    rows: dict[int, dict] = {}

    def probe(b: int) -> dict:
        if b not in rows:
            r = pair(client, token, b)
            r["timestamp_ns"] = client.block_header(b)["timestamp_ns"]
            rows[b] = r
        return rows[b]

    for b in range(DENSE_START, DENSE_END + 1, DENSE_STEP):
        try:
            probe(b)
        except ViewError as e:  # missing block at that height: skip
            log(f"series skip {b}: {e.kind}")
    log(f"series dense: {len(rows)} points")

    def bisect(pred, lo: int, hi: int) -> int:
        return bisect_first(probe, pred, lo, hi)

    dense = sorted(rows)
    for t in GAP_THRESHOLDS_RAW:
        pred = lambda r, t=t: _gap(r) >= t  # noqa: E731
        prev = None
        for b in dense:
            if pred(rows[b]):
                if prev is not None:
                    bisect(pred, prev, b)
                break
            prev = b
    # closure: first block after the peak where the gap returns to <= 0
    peak = max(dense, key=lambda b: _gap(rows[b]))
    prev = None
    for b in [x for x in dense if x > peak]:
        if _gap(rows[b]) <= 0:
            bisect(lambda r: _gap(r) <= 0, prev or peak, b)
            break
        prev = b
    out = [dict(block_height=b, **{k: v for k, v in rows[b].items() if k != "block_height"}) for b in sorted(rows)]
    _write(f"{data}/series/incident_token.json", {"token": token, "collected_at": _now(), "rows": out})
    log(f"series total: {len(out)} points")


def collect_pause(client: Client, data: str) -> None:
    rows: dict[int, dict] = {}

    def probe(b: int) -> bool:
        if b not in rows:
            p = client.view(INTENTS, "pa_is_paused", {"key": "ALL"}, b)
            rows[b] = {"paused": bool(p), "timestamp_ns": client.block_header(b)["timestamp_ns"]}
        return rows[b]["paused"]

    for b in range(DENSE_START, DENSE_END + 1, DENSE_STEP * 4):
        try:
            probe(b)
        except ViewError as e:
            log(f"pause skip {b}: {e.kind}")
    dense = sorted(rows)
    for a, b in zip(dense, dense[1:]):
        if rows[a]["paused"] != rows[b]["paused"]:
            target = rows[b]["paused"]
            bisect_first(probe, lambda p, target=target: p == target, a, b)
    out = [{"block_height": b, **rows[b]} for b in sorted(rows)]
    _write(f"{data}/series/paused_all.json", {"contract": INTENTS, "method": "pa_is_paused", "args": {"key": "ALL"}, "collected_at": _now(), "rows": out})
    log(f"pause series: {len(out)} points")


def collect_all(data: str = "data", rate: float = 4.0, what: str = "all") -> None:
    client = Client(rate=rate)
    if what in ("all", "universe"):
        ids = collect_universe(client, data)
    else:
        with open(f"{data}/universe.json") as f:
            ids = json.load(f)["token_ids"]
    if what in ("all", "meta"):
        collect_metadata(client, data, ids)
    if what in ("all", "series"):
        collect_series(client, data)
    if what in ("all", "pause"):
        collect_pause(client, data)
    if what in ("all", "scans"):
        grid = list(range(WINDOW_START, WINDOW_END + 1, GRID_STEP))
        collect_scans(client, data, ids, grid + [None])
    if what in ("all", "scans", "repair"):
        repair_scans(client, data)
    log(f"done. rpc calls={client.calls} cache_hits={client.cache_hits}")
