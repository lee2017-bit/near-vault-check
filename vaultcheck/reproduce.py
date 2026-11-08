"""Offline: rebuild every published number from the committed snapshots in data/.

No network, no keys, standard library only. Writes out/report.json and out/report.html.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os

from . import manifest
from .alarm import ALARM, BACKED, DRIFT, STANDING, UNVERIFIABLE, classify_scan

THRESHOLDS_USD = [0, 1_000, 10_000, 100_000, 1_000_000]  # 0 = first unbacked unit


def _load(path: str):
    with open(path) as f:
        return json.load(f)


def iso(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1e9, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_utc(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def _ts(ns: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ns / 1e9, dt.timezone.utc)


def load_context(data: str) -> dict:
    meta = {k: dict(v) for k, v in _load(f"{data}/token_meta.json")["tokens"].items()}
    prices = {}
    api_path = f"{data}/token_api.json"
    if os.path.exists(api_path):
        for it in _load(api_path)["items"]:
            tid = it["defuse_asset_id"]
            if it.get("price") is not None:
                prices[tid] = it["price"]
            m = meta.setdefault(tid, {})
            if m.get("decimals") is None and it.get("decimals") is not None:  # fill gaps from the token API
                m.update({"decimals": it["decimals"], "symbol": m.get("symbol") or it.get("symbol")})
    registry = _load(f"{data}/registry.json")["tokens"] if os.path.exists(f"{data}/registry.json") else {}
    return {"meta": meta, "prices": prices, "registry": registry}


def incident_timeline(series: dict, incident: dict, meta: dict) -> dict:
    token = series["token"]
    dec = int((meta.get(token) or {}).get("decimals") or 18)
    rows = sorted(series["rows"], key=lambda r: r["block_height"])
    for r in rows:
        r["gap_raw"] = int(r["ledger"]) - int(r["vault"])
        r["gap"] = r["gap_raw"] / 10**dec
    events = {e["key"]: parse_utc(e["time"]) for e in incident["events_utc"]}
    identified = events["identified"]

    crossings = []
    for thr in THRESHOLDS_USD:
        raw = 1 if thr == 0 else thr * 10**dec  # stablecoin: 1 token = 1 USD
        hit = next((r for r in rows if r["gap_raw"] >= raw), None)
        if hit is None:
            crossings.append({"threshold_usd": thr, "block": None})
            continue
        t = _ts(hit["timestamp_ns"])
        crossings.append(
            {
                "threshold_usd": thr,
                "block": hit["block_height"],
                "time_utc": iso(hit["timestamp_ns"]),
                "gap_usd": round(hit["gap"], 2),
                "hours_before_identified": round((identified - t).total_seconds() / 3600, 2),
            }
        )
    peak = max(rows, key=lambda r: r["gap_raw"])
    after = [r for r in rows if r["block_height"] > peak["block_height"]]
    closure = next((r for r in after if r["gap_raw"] <= 0), None)
    last_pos = None
    if closure:
        before = [r for r in after if r["block_height"] < closure["block_height"] and r["gap_raw"] > 0]
        last_pos = before[-1] if before else peak
    at_ident = max((r for r in rows if _ts(r["timestamp_ns"]) <= identified), key=lambda r: r["block_height"])
    # plateaus on the way up: a gap level seen in 2+ consecutive snapshots, rising until the peak
    plateaus: list[float] = []
    up = [r for r in rows if r["block_height"] <= peak["block_height"]]
    for a, b in zip(up, up[1:]):
        if a["gap_raw"] == b["gap_raw"] and a["gap_raw"] > 0 and (not plateaus or a["gap"] > plateaus[-1]):
            plateaus.append(round(a["gap"], 2))
    return {
        "token": token,
        "decimals": dec,
        "points": len(rows),
        "first_block": rows[0]["block_height"],
        "last_block": rows[-1]["block_height"],
        "crossings": crossings,
        "peak": {"block": peak["block_height"], "time_utc": iso(peak["timestamp_ns"]), "gap_usd": round(peak["gap"], 2),
                 "ledger": round(int(peak["ledger"]) / 10**dec, 2), "vault": round(int(peak["vault"]) / 10**dec, 2)},
        "at_identification": {"block": at_ident["block_height"], "time_utc": iso(at_ident["timestamp_ns"]), "gap_usd": round(at_ident["gap"], 2)},
        "plateaus_usd": plateaus,
        "closure": None
        if not closure
        else {"block": closure["block_height"], "time_utc": iso(closure["timestamp_ns"]), "gap_usd": round(closure["gap"], 2),
              "last_unbacked_block": last_pos["block_height"], "last_unbacked_gap_usd": round(last_pos["gap"], 2)},
        "series": [{"block": r["block_height"], "t": iso(r["timestamp_ns"]), "gap_usd": round(r["gap"], 2)} for r in rows],
    }


def pause_flips(pause: dict, incident: dict) -> list[dict]:
    rows = sorted(pause["rows"], key=lambda r: r["block_height"])
    events = {e["key"]: parse_utc(e["time"]) for e in incident["events_utc"]}
    out = []
    for a, b in zip(rows, rows[1:]):
        if a["paused"] != b["paused"]:
            key = "paused" if b["paused"] else "unpaused"
            t = _ts(b["timestamp_ns"])
            out.append({"to": "paused" if b["paused"] else "unpaused", "block": b["block_height"], "time_utc": iso(b["timestamp_ns"]),
                        "postmortem_time_utc": events[key].strftime("%Y-%m-%d %H:%M") if key in events else None,
                        "minutes_from_postmortem": round((t - events[key]).total_seconds() / 60, 1) if key in events else None})
    return out


def grid(data: str, ctx: dict, threshold_usd: float = 1000.0) -> list[dict]:
    files = sorted(glob.glob(f"{data}/scans/*.json"), key=lambda p: int(os.path.basename(p)[:-5]))
    scans = [_load(p) for p in files]
    if not scans:
        return []
    baseline = scans[0]
    out = []
    for s in scans:
        verdicts = classify_scan(s, baseline, ctx["meta"], ctx["prices"], threshold_usd)
        counts = {k: 0 for k in (ALARM, DRIFT, STANDING, BACKED, UNVERIFIABLE)}
        for v in verdicts:
            counts[v.status] += 1
        out.append(
            {
                "block": s["block_height"],
                "time_utc": iso(s["timestamp_ns"]),
                "tokens": len(verdicts),
                "counts": counts,
                "alarms": [{"token": v.token, "symbol": v.symbol, "growth_usd": None if v.growth_usd is None else round(v.growth_usd, 2),
                            "units": None if v.units is None else round(v.units, 6), "note": v.note,
                            "registry": ctx["registry"].get(v.token, {}).get("class")}
                           for v in verdicts if v.status == ALARM],
                "standing": [{"token": v.token, "symbol": v.symbol, "registry": ctx["registry"].get(v.token, {}).get("class")}
                             for v in verdicts if v.status == STANDING],
            }
        )
    return out


def naive_alarms(data: str, ctx: dict) -> int | None:
    """How many ids a rule with no baseline (ledger <= vault, $1k / 1%) flags on the first scan."""
    files = sorted(glob.glob(f"{data}/scans/*.json"), key=lambda p: int(os.path.basename(p)[:-5]))
    if not files:
        return None
    first = _load(files[0])
    return sum(1 for v in classify_scan(first, None, ctx["meta"], ctx["prices"]) if v.status == ALARM)


def reproduce(data: str = "data", out: str = "out") -> int:
    problems = manifest.verify(data)
    ctx = load_context(data)
    incident = _load(f"{data}/incident.json")
    timeline = incident_timeline(_load(f"{data}/series/incident_token.json"), incident, ctx["meta"])
    flips = pause_flips(_load(f"{data}/series/paused_all.json"), incident)
    scans = grid(data, ctx)
    report = {
        "manifest_ok": not problems,
        "manifest_problems": problems,
        "incident": {k: v for k, v in timeline.items() if k != "series"},
        "pause_flips": flips,
        "scans": scans,
        "naive_baseline_alarms": naive_alarms(data, ctx),
        "sources": incident["sources"],
    }
    os.makedirs(out, exist_ok=True)
    with open(f"{out}/report.json", "w") as f:
        json.dump(report, f, indent=1)
    from .report import write_html

    write_html(report, timeline["series"], incident, f"{out}/report.html")
    from .demo import write_demo

    write_demo(report, timeline["series"], incident, f"{out}/demo.html")
    print_summary(report)
    return 0 if not problems else 1


def _fmt_usd(x) -> str:
    return "-" if x is None else f"${x:,.0f}"


def print_summary(r: dict) -> None:
    inc = r["incident"]
    print("Vault Check: reproduce (offline, from data/)")
    print(f"  data integrity: {'OK' if r['manifest_ok'] else 'FAILED ' + '; '.join(r['manifest_problems'][:5])}")
    print(f"\nIncident token {inc['token']}  ({inc['points']} snapshots, blocks {inc['first_block']}..{inc['last_block']})")
    print("  ledger = intents.near mt_supply   vault = v2_1.omni.hot.tg mt_balance_of(intents.near)")
    print(f"  {'alarm threshold':>16} | {'first block':>11} | {'time (UTC)':19} | {'unbacked':>12} | lead vs team")
    for c in inc["crossings"]:
        name = "first unit" if c["threshold_usd"] == 0 else _fmt_usd(c["threshold_usd"])
        if c["block"] is None:
            print(f"  {name:>16} | {'never':>11} |")
            continue
        print(f"  {name:>16} | {c['block']:>11} | {c['time_utc']} | {_fmt_usd(c['gap_usd']):>12} | {c['hours_before_identified']:+.1f} h")
    p = inc["peak"]
    print(f"  peak unbacked: {_fmt_usd(p['gap_usd'])} at block {p['block']} ({p['time_utc']}): ledger {p['ledger']:,.0f} vs vault {p['vault']:,.0f}")
    a = inc["at_identification"]
    print(f"  unbacked when the team identified the problem (08:04): {_fmt_usd(a['gap_usd'])} (block {a['block']})")
    if inc["closure"]:
        c = inc["closure"]
        print(f"  gap closed: block {c['block']} ({c['time_utc']}); last unbacked {_fmt_usd(c['last_unbacked_gap_usd'])} at {c['last_unbacked_block']}")
    print("\nOn-chain pause flag pa_is_paused(ALL) vs post-mortem:")
    for f in r["pause_flips"]:
        print(f"  -> {f['to']:8} block {f['block']} {f['time_utc']}  (post-mortem {f['postmortem_time_utc']}, {f['minutes_from_postmortem']:+.1f} min)")
    print("\nAll fungible tokens, alarm at $1,000 growth of an unbacked gap vs the first scan:")
    for s in r["scans"]:
        c = s["counts"]
        alarms = ", ".join(f"{a['symbol'] or a['token'][:24]} {_fmt_usd(a['growth_usd'])}" for a in s["alarms"]) or "none"
        print(f"  {s['block']} {s['time_utc'][:16]}  backed {c['backed']:3} standing {c['standing']:2} drift {c['drift']:2} unverifiable {c['unverifiable']:3}  ALARM: {alarms}")
