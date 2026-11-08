"""Token universe of the NEAR Intents contract and how to find each token's vault.

intents.near is a NEP-245 multi-token ledger. Its token ids name where the real
asset sits:
  nep141:<ft_contract>                  -> <ft_contract>.ft_balance_of(intents.near)
  nep245:<mt_contract>:<inner_token_id> -> <mt_contract>.mt_balance_of(intents.near, inner)
  nep171:<nft_contract>:<token_id>      -> non-fungible; out of scope (one owner, no amount)
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from .rpc import USER_AGENT, Client, ViewError

INTENTS = "intents.near"
TOKEN_API = "https://api-mng-console.chaindefuser.com/api/tokens"


@dataclass(frozen=True)
class TokenRef:
    token_id: str  # full id as used by intents.near
    standard: str  # nep141 | nep245 | nep171
    contract: str  # contract that holds the real balance
    inner: str | None = None  # inner id on a NEP-245 contract

    @property
    def fungible(self) -> bool:
        return self.standard in ("nep141", "nep245")


def parse_token_id(token_id: str) -> TokenRef:
    standard, _, rest = token_id.partition(":")
    if standard == "nep141":
        return TokenRef(token_id, standard, rest)
    if standard in ("nep245", "nep171"):
        contract, _, inner = rest.partition(":")
        return TokenRef(token_id, standard, contract, inner)
    raise ValueError(f"unknown token id format: {token_id}")


def list_token_ids(client: Client, block: int | None = None, page: int = 200) -> list[str]:
    """Enumerate every token id on intents.near (includes NFTs)."""
    out: list[str] = []
    start = 0
    while True:
        chunk = client.view(INTENTS, "mt_tokens", {"from_index": str(start), "limit": page}, block)
        if not chunk:
            break
        out.extend(t["token_id"] for t in chunk)
        if len(chunk) < page:
            break
        start += page
    return out


def fungible_universe(client: Client, block: int | None = None) -> list[str]:
    ids = list_token_ids(client, block)
    return sorted(t for t in ids if parse_token_id(t).fungible)


def fetch_token_api(url: str = TOKEN_API) -> list[dict]:
    """Public, keyless list of ~220 Intents assets with decimals and USD price."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    return data["items"] if isinstance(data, dict) and "items" in data else data


def fetch_metadata(client: Client, token_ids: list[str], block: int | None = None) -> dict:
    """Decimals and symbol for each fungible token, read from its own contract."""
    meta: dict[str, dict] = {}
    by_mt: dict[str, list[TokenRef]] = {}
    for tid in token_ids:
        ref = parse_token_id(tid)
        if ref.standard == "nep141":
            try:
                m = client.view(ref.contract, "ft_metadata", {}, block)
                meta[tid] = {"symbol": m.get("symbol"), "decimals": m.get("decimals"), "name": m.get("name")}
            except ViewError as e:
                meta[tid] = {"error": e.kind}
        elif ref.standard == "nep245":
            by_mt.setdefault(ref.contract, []).append(ref)
    for contract, refs in by_mt.items():
        for i in range(0, len(refs), 50):
            part = refs[i : i + 50]
            try:
                rows = client.view(contract, "mt_metadata_base_by_token_id", {"token_ids": [r.inner for r in part]}, block)
            except ViewError as e:
                for r in part:
                    meta[r.token_id] = {"error": e.kind}
                continue
            for r, m in zip(part, rows or []):
                if m:
                    meta[r.token_id] = {"symbol": m.get("symbol"), "decimals": m.get("decimals"), "name": m.get("name")}
                else:
                    meta[r.token_id] = {"error": "NoMetadata"}
    return meta
