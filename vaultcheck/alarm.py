"""Classify each token: is what Intents owes (ledger) still backed by what it holds (vault)?

A naive rule `ledger <= vault` is red on day one: a dozen ids carry small, old,
explained gaps (test tokens, dust, ids whose vault lives elsewhere). So the alarm
is baseline-aware: it fires on *growth* of an unbacked gap beyond a USD threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

STABLE_SYMBOLS = {"USDT", "USDT.E", "USDC", "USDC.E", "USDt", "DAI", "USD1", "PYUSD", "FDUSD"}

ALARM = "ALARM"  # unbacked gap grew beyond the threshold since the baseline
DRIFT = "drift"  # unbacked gap grew, but below the threshold
STANDING = "standing"  # unbacked gap that already existed at the baseline, not growing
BACKED = "backed"  # ledger <= vault (a vault surplus is fine)
UNVERIFIABLE = "unverifiable"  # one side could not be read at this block


@dataclass
class Verdict:
    token: str
    status: str
    gap: int | None  # ledger - vault, raw units (positive = unbacked)
    growth: int | None  # gap growth vs baseline, raw units
    growth_usd: float | None
    units: float | None  # growth in whole tokens
    symbol: str | None
    note: str = ""


def price_for(token: str, meta: dict, prices: dict) -> float | None:
    if token in prices and prices[token] is not None:
        return float(prices[token])
    sym = (meta.get(token) or {}).get("symbol") or ""
    if sym.upper() in {s.upper() for s in STABLE_SYMBOLS}:
        return 1.0
    return None


def decimals_for(token: str, meta: dict) -> int | None:
    d = (meta.get(token) or {}).get("decimals")
    return int(d) if d is not None else None


def classify(
    row: dict,
    baseline_gap: int | None,
    meta: dict,
    prices: dict,
    threshold_usd: float = 1000.0,
    unpriced_rel: float = 0.01,
) -> Verdict:
    token = row["token"]
    sym = (meta.get(token) or {}).get("symbol")
    if row.get("ledger") is None or row.get("vault") is None:
        return Verdict(token, UNVERIFIABLE, None, None, None, None, sym, row.get("error", "missing"))
    ledger, vault = int(row["ledger"]), int(row["vault"])
    gap = ledger - vault
    if gap <= 0:
        return Verdict(token, BACKED, gap, 0, 0.0, 0.0, sym)
    base = max(baseline_gap or 0, 0)
    growth = gap - base
    dec = decimals_for(token, meta)
    units = growth / 10**dec if dec is not None else None
    price = price_for(token, meta, prices)
    growth_usd = units * price if (units is not None and price is not None) else None
    if growth <= 0:
        return Verdict(token, STANDING, gap, growth, growth_usd, units, sym)
    if growth_usd is not None:
        status = ALARM if growth_usd >= threshold_usd else DRIFT
        return Verdict(token, status, gap, growth, growth_usd, units, sym)
    # no price: fall back to a relative rule on the ledger size
    rel = growth / ledger if ledger else 1.0
    status = ALARM if rel >= unpriced_rel else DRIFT
    return Verdict(token, status, gap, growth, None, units, sym, f"unpriced; growth {rel:.2%} of ledger")


def classify_scan(scan: dict, baseline: dict | None, meta: dict, prices: dict, threshold_usd: float = 1000.0) -> list[Verdict]:
    base_gaps: dict[str, int] = {}
    if baseline:
        for r in baseline["rows"]:
            if r.get("ledger") is not None and r.get("vault") is not None:
                base_gaps[r["token"]] = int(r["ledger"]) - int(r["vault"])
    return [classify(r, base_gaps.get(r["token"]), meta, prices, threshold_usd) for r in scan["rows"]]
