import unittest

from vaultcheck.alarm import ALARM, BACKED, DRIFT, STANDING, UNVERIFIABLE, classify
from vaultcheck.tokens import parse_token_id

USDT_BSC = "nep245:v2_1.omni.hot.tg:56_2CMMyVTGZkeyNZTSvS5sarzfir6g"
META = {
    USDT_BSC: {"symbol": "USDT", "decimals": 18},
    "nep141:usdt.tether-token.near": {"symbol": "USDt", "decimals": 6},
    "nep141:wrap.near": {"symbol": "wNEAR", "decimals": 24},
    "nep141:mystery.near": {"symbol": "MYST", "decimals": 0},
}
PRICES = {"nep141:wrap.near": 4.0}


def row(token, ledger, vault):
    return {"token": token, "ledger": None if ledger is None else str(ledger), "vault": None if vault is None else str(vault)}


class TokenIds(unittest.TestCase):
    def test_parse(self):
        r = parse_token_id(USDT_BSC)
        self.assertEqual((r.standard, r.contract, r.inner), ("nep245", "v2_1.omni.hot.tg", "56_2CMMyVTGZkeyNZTSvS5sarzfir6g"))
        r = parse_token_id("nep141:wrap.near")
        self.assertEqual((r.standard, r.contract, r.inner), ("nep141", "wrap.near", None))
        self.assertFalse(parse_token_id("nep171:nft.near:42").fungible)


class Classify(unittest.TestCase):
    def test_vault_surplus_is_backed(self):
        v = classify(row("nep141:usdt.tether-token.near", 100, 120), None, META, PRICES)
        self.assertEqual(v.status, BACKED)

    def test_decimals_differ_per_token(self):
        # 10 USDT on BSC is 10 * 10**18 raw; on NEAR native USDT it is 10 * 10**6 raw.
        v = classify(row(USDT_BSC, 10 * 10**18, 0), None, META, PRICES)
        self.assertAlmostEqual(v.growth_usd, 10.0)
        v = classify(row("nep141:usdt.tether-token.near", 10 * 10**6, 0), None, META, PRICES)
        self.assertAlmostEqual(v.growth_usd, 10.0)

    def test_threshold(self):
        self.assertEqual(classify(row(USDT_BSC, 999 * 10**18, 0), None, META, PRICES).status, DRIFT)
        self.assertEqual(classify(row(USDT_BSC, 1000 * 10**18, 0), None, META, PRICES).status, ALARM)

    def test_baseline_gap_is_standing_not_alarm(self):
        base = 5000 * 10**18
        self.assertEqual(classify(row(USDT_BSC, base, 0), base, META, PRICES).status, STANDING)
        self.assertEqual(classify(row(USDT_BSC, base + 2000 * 10**18, 0), base, META, PRICES).status, ALARM)

    def test_priced_by_api(self):
        v = classify(row("nep141:wrap.near", 300 * 10**24, 0), None, META, PRICES)
        self.assertEqual(v.status, ALARM)
        self.assertAlmostEqual(v.growth_usd, 1200.0)

    def test_unpriced_uses_relative_rule(self):
        self.assertEqual(classify(row("nep141:mystery.near", 1000, 995), None, META, PRICES).status, DRIFT)
        self.assertEqual(classify(row("nep141:mystery.near", 1000, 900), None, META, PRICES).status, ALARM)

    def test_unreadable_side(self):
        self.assertEqual(classify(row(USDT_BSC, 1, None), None, META, PRICES).status, UNVERIFIABLE)


if __name__ == "__main__":
    unittest.main()
