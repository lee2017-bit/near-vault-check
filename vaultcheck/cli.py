"""Command line: python -m vaultcheck {reproduce,live,collect}"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vaultcheck", description="Public, keyless reserve check for NEAR Intents.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("reproduce", help="offline: rebuild every published number from data/ (no network)")
    r.add_argument("--data", default="data")
    r.add_argument("--out", default="out")

    lv = sub.add_parser("live", help="online: check the latest block now (keyless public RPC)")
    lv.add_argument("--data", default="data")
    lv.add_argument("--top", type=int, default=0, help="only the N most valuable tokens (0 = all 717)")
    lv.add_argument("--rate", type=float, default=4.0, help="max RPC calls per second")
    lv.add_argument("--threshold-usd", type=float, default=1000.0)

    c = sub.add_parser("collect", help="maintainer: re-download data/ snapshots from public RPC (slow)")
    c.add_argument("--data", default="data")
    c.add_argument("--rate", type=float, default=4.0)
    c.add_argument("--what", default="all", choices=["all", "universe", "meta", "series", "pause", "scans", "repair"])

    rd = sub.add_parser("readme", help="maintainer: regenerate README result sections from out/report.json")
    rd.add_argument("--report", default="out/report.json")

    a = p.parse_args(argv)
    if a.cmd == "readme":
        from .readme import update

        update(report=a.report)
        return 0
    if a.cmd == "collect":
        from .collect import collect_all

        collect_all(a.data, a.rate, a.what)
        return 0
    if a.cmd == "reproduce":
        from .reproduce import reproduce

        return reproduce(a.data, a.out)
    if a.cmd == "live":
        from .live import live

        return live(a.data, a.top, a.rate, a.threshold_usd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
