"""Online: run the check against the latest final block with keyless public RPC."""

from __future__ import annotations

import glob
import json
import os

from .alarm import ALARM, BACKED, DRIFT, STANDING, UNVERIFIABLE, classify_scan
from .reproduce import iso, load_context
from .rpc import Client
from .scan import scan


def _latest_scan(data: str) -> dict | None:
    files = sorted(glob.glob(f"{data}/scans/*.json"), key=lambda p: int(os.path.basename(p)[:-5]))
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


def _value_usd(row: dict, meta: dict, prices: dict) -> float:
    tid = row["token"]
    dec = (meta.get(tid) or {}).get("decimals")
    if row.get("ledger") is None or dec is None or tid not in prices:
        return 0.0
    return int(row["ledger"]) / 10 ** int(dec) * float(prices[tid])


def live(data: str = "data", top: int = 0, rate: float = 4.0, threshold_usd: float = 1000.0, out: str = "out") -> int:
    ctx = load_context(data)
    with open(f"{data}/universe.json") as f:
        ids = json.load(f)["token_ids"]
    baseline = _latest_scan(data)
    if top and baseline:
        ranked = sorted(baseline["rows"], key=lambda r: _value_usd(r, ctx["meta"], ctx["prices"]), reverse=True)
        keep = {r["token"] for r in ranked[:top]}
        ids = [t for t in ids if t in keep]
    client = Client(rate=rate)
    print(f"Vault Check live: {len(ids)} tokens, baseline = committed scan {baseline['block_height'] if baseline else 'none'}")
    snap = scan(client, ids, None)
    verdicts = classify_scan(snap, baseline, ctx["meta"], ctx["prices"], threshold_usd)
    counts = {k: 0 for k in (ALARM, DRIFT, STANDING, BACKED, UNVERIFIABLE)}
    for v in verdicts:
        counts[v.status] += 1
    print(f"block {snap['block_height']} ({iso(snap['timestamp_ns'])} UTC), {client.calls} RPC calls")
    print("  " + "  ".join(f"{k}: {n}" for k, n in counts.items()))
    by_value = sorted(snap["rows"], key=lambda r: _value_usd(r, ctx["meta"], ctx["prices"]), reverse=True)[:10]
    status = {v.token: v for v in verdicts}
    print("\n  largest balances held for users:")
    for r in by_value:
        v = status[r["token"]]
        print(f"   {(v.symbol or r['token'])[:14]:14} ${_value_usd(r, ctx['meta'], ctx['prices']):>14,.0f}  {v.status}")
    alarms = [v for v in verdicts if v.status == ALARM]
    for v in alarms:
        usd = "unpriced" if v.growth_usd is None else f"${v.growth_usd:,.0f}"
        print(f"  ALARM {v.symbol or v.token}: unbacked gap grew by {v.units} tokens ({usd}) since the baseline")
    os.makedirs(out, exist_ok=True)
    with open(f"{out}/live_{snap['block_height']}.json", "w") as f:
        json.dump(snap, f)
    print(f"\n  {'ALARM' if alarms else 'OK: no unbacked gap grew past'} ${threshold_usd:,.0f}. Raw snapshot: {out}/live_{snap['block_height']}.json")
    return 1 if alarms else 0
