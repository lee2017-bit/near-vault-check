"""Read both sides of the invariant at one block.

ledger(token) = intents.near.mt_supply(token)      what Intents owes all its users
vault(token)  = balance of intents.near on the token's own contract
The invariant a custodial ledger must keep: ledger <= vault.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .rpc import DETERMINISTIC_KINDS, Client, TransportError, ViewError
from .tokens import INTENTS, parse_token_id


def read_ledger(client: Client, token_ids: list[str], block: int | None, chunk: int = 50) -> dict:
    out: dict[str, str | None] = {}
    for i in range(0, len(token_ids), chunk):
        part = token_ids[i : i + chunk]
        try:
            vals = client.view(INTENTS, "mt_batch_supply", {"token_ids": part}, block)
            out.update(zip(part, vals))
        except ViewError:
            for t in part:  # isolate the bad id
                try:
                    out[t] = client.view(INTENTS, "mt_supply", {"token_id": t}, block)
                except ViewError:
                    out[t] = None
    return out


def _ft_vault(client: Client, contract: str, block: int | None, attempts: int = 3):
    err = None
    for i in range(attempts):
        try:
            return client.view(contract, "ft_balance_of", {"account_id": INTENTS}, block), None
        except ViewError as e:
            if e.kind in DETERMINISTIC_KINDS:  # a fact about the chain at this block
                return None, e.kind
            err = e.kind  # transient server-side error: retry
        except TransportError as e:
            err = "Transport:" + str(e)[:80]
        time.sleep(2 * (i + 1))
    return None, err


def read_vault(client: Client, token_ids: list[str], block: int | None, workers: int = 4) -> tuple[dict, dict]:
    values: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    ft = [parse_token_id(t) for t in token_ids if t.startswith("nep141:")]
    mt: dict[str, list] = {}
    for t in token_ids:
        if t.startswith("nep245:"):
            ref = parse_token_id(t)
            mt.setdefault(ref.contract, []).append(ref)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {r.token_id: pool.submit(_ft_vault, client, r.contract, block) for r in ft}
        for tid, fut in futures.items():
            v, err = fut.result()
            values[tid] = v
            if err:
                errors[tid] = err

    for contract, refs in mt.items():
        for i in range(0, len(refs), 50):
            part = refs[i : i + 50]
            try:
                vals = client.view(contract, "mt_batch_balance_of", {"account_id": INTENTS, "token_ids": [r.inner for r in part]}, block)
                for r, v in zip(part, vals):
                    values[r.token_id] = v
            except ViewError:
                for r in part:
                    try:
                        values[r.token_id] = client.view(contract, "mt_balance_of", {"account_id": INTENTS, "token_id": r.inner}, block)
                    except ViewError as e:
                        values[r.token_id] = None
                        errors[r.token_id] = e.kind
    return values, errors


def scan(client: Client, token_ids: list[str], block: int | None = None, workers: int = 4) -> dict:
    """Full reconciliation snapshot at one block (or the latest final block)."""
    header = client.block_header(block)
    height = header["height"]  # pin 'final' to a concrete height so both sides match
    t0 = time.time()
    ledger = read_ledger(client, token_ids, height)
    t1 = time.time()
    vault, errors = read_vault(client, token_ids, height, workers=workers)
    t2 = time.time()
    rows = []
    for tid in token_ids:
        row = {"token": tid, "ledger": ledger.get(tid), "vault": vault.get(tid)}
        if tid in errors:
            row["error"] = errors[tid]
        rows.append(row)
    return {
        "block_height": height,
        "block_hash": header["hash"],
        "timestamp_ns": header["timestamp_ns"],
        "contract": INTENTS,
        "endpoint": client.endpoint,
        "seconds": {"ledger": round(t1 - t0, 1), "vault": round(t2 - t1, 1)},
        "rows": rows,
    }


def pair(client: Client, token_id: str, block: int) -> dict:
    """Ledger and vault for a single token at one block (two view calls)."""
    ref = parse_token_id(token_id)
    ledger = client.view(INTENTS, "mt_supply", {"token_id": token_id}, block)
    if ref.standard == "nep141":
        vault = client.view(ref.contract, "ft_balance_of", {"account_id": INTENTS}, block)
    else:
        vault = client.view(ref.contract, "mt_balance_of", {"account_id": INTENTS, "token_id": ref.inner}, block)
    return {"block_height": block, "ledger": ledger, "vault": vault}
