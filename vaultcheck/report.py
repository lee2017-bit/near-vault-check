"""Single-file HTML report (inline SVG, no external assets) built from out/report.json."""

from __future__ import annotations

import datetime as dt
import html
import math

CSS = """
:root{--bg:#ffffff;--fg:#1d1d1f;--muted:#6e6e73;--grid:#e5e5ea;--line:#d70015;--fill:rgba(215,0,21,.10);
--ok:#1a7f37;--warn:#b35900;--ev:#5856d6;--card:#f5f5f7}
@media (prefers-color-scheme:dark){:root{--bg:#111113;--fg:#f2f2f7;--muted:#98989f;--grid:#2c2c30;--line:#ff453a;
--fill:rgba(255,69,58,.15);--ok:#30d158;--warn:#ff9f0a;--ev:#a5a3ff;--card:#1c1c1f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;line-height:1.25;margin:8px 0 6px}
h2{font-size:18px;margin:32px 0 8px}.lead{color:var(--muted);margin:0 0 16px}.card{background:var(--card);border-radius:12px;padding:12px 14px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid)}
th{color:var(--muted);font-weight:600}td.n,th.n{text-align:right}.ok{color:var(--ok)}.bad{color:var(--line);font-weight:600}.warn{color:var(--warn)}
.scroll{overflow-x:auto}.scroll svg{min-width:680px}td{white-space:nowrap}svg text{fill:var(--muted);font-size:11px}code{font-size:13px}a{color:var(--ev)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:16px 0}
.kpi b{display:block;font-size:22px}.kpi span{color:var(--muted);font-size:13px}
"""


def _t(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)


def _usd(x) -> str:
    return "-" if x is None else f"${x:,.0f}"


def chart(series: list[dict], incident: dict, crossings: list[dict]) -> str:
    W, H, L, R, T, B = 1000, 360, 64, 16, 16, 40
    pts = [(_t(p["t"]), p["gap_usd"]) for p in series]
    t0 = dt.datetime(2026, 9, 29, 0, tzinfo=dt.timezone.utc)
    t1 = dt.datetime(2026, 10, 3, 0, tzinfo=dt.timezone.utc)
    pts = [p for p in pts if t0 <= p[0] <= t1]
    span = (t1 - t0).total_seconds()

    def x(t):
        return L + (t - t0).total_seconds() / span * (W - L - R)

    ymin, ymax = 0.0, 7.0  # log10 USD: $1 .. $10M

    def y(v):
        lv = math.log10(v) if v >= 1 else ymin
        return T + (1 - (lv - ymin) / (ymax - ymin)) * (H - T - B)

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Unbacked USDT inside intents.near over time">']
    for k in range(0, 8):
        yy = y(10**k)
        label = ["$1", "$10", "$100", "$1k", "$10k", "$100k", "$1M", "$10M"][k]
        out.append(f'<line x1="{L}" x2="{W-R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--grid)"/><text x="{L-6}" y="{yy+4:.1f}" text-anchor="end">{label}</text>')
    d = t0
    while d <= t1:
        xx = x(d)
        out.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{T}" y2="{H-B}" stroke="var(--grid)"/><text x="{xx:.1f}" y="{H-B+16}" text-anchor="middle">{d:%b %d}</text>')
        d += dt.timedelta(days=1)
    # step line of the unbacked amount
    path = []
    prev_y = None
    for t, v in pts:
        xx, yy = x(t), y(v)
        if prev_y is None:
            path.append(f"M{xx:.1f},{yy:.1f}")
        else:
            path.append(f"H{xx:.1f}V{yy:.1f}")
        prev_y = yy
    if path:
        area = "".join(path) + f"H{x(pts[-1][0]):.1f}V{y(0):.1f}H{x(pts[0][0]):.1f}Z"
        out.append(f'<path d="{area}" fill="var(--fill)" stroke="none"/>')
        out.append(f'<path d="{"".join(path)}" fill="none" stroke="var(--line)" stroke-width="2"/>')
    # post-mortem events
    evs = {e["key"]: e for e in incident["events_utc"]}
    # (event keys drawn as lines, one label for the group)
    marks = [(("identified", "paused"), "identified 08:04, paused 08:33"), (("fix_deployed",), "fix deployed 20:31")]
    for i, (keys, label) in enumerate(marks):
        xs = []
        for key in keys:
            if key in evs:
                t = dt.datetime.strptime(evs[key]["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
                xs.append(x(t))
                out.append(f'<line x1="{xs[-1]:.1f}" x2="{xs[-1]:.1f}" y1="{T}" y2="{H-B}" stroke="var(--ev)" stroke-dasharray="4 3"/>')
        if xs:
            right = max(xs)
            if right > W - 220:  # keep the label inside the plot
                out.append(f'<text x="{min(xs)-4:.1f}" y="{H-B-8-14*i}" text-anchor="end" style="fill:var(--ev)">{html.escape(label)}</text>')
            else:
                out.append(f'<text x="{right+4:.1f}" y="{H-B-8-14*i}" style="fill:var(--ev)">{html.escape(label)}</text>')
    # alarm firing points
    for c in crossings:
        if c.get("block") and c["threshold_usd"] in (0, 1000, 1_000_000):
            t = _t(c["time_utc"])
            if t0 <= t <= t1:
                v = max(c["gap_usd"], 1)
                name = "first unit" if c["threshold_usd"] == 0 else _usd(c["threshold_usd"])
                out.append(f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="5" fill="var(--line)"/>'
                           f'<text x="{x(t)+7:.1f}" y="{y(v)-7:.1f}" style="fill:var(--fg)">alarm at {name}</text>')
    out.append("</svg>")
    return "".join(out)


def write_html(report: dict, series: list[dict], incident: dict, path: str) -> None:
    inc = report["incident"]
    first = next((c for c in inc["crossings"] if c["threshold_usd"] == 1000 and c["block"]), None)
    rows = []
    for c in inc["crossings"]:
        name = "first unbacked unit" if c["threshold_usd"] == 0 else _usd(c["threshold_usd"])
        if not c["block"]:
            rows.append(f"<tr><td>{name}</td><td colspan=4>never crossed</td></tr>")
            continue
        rows.append(f'<tr><td>{name}</td><td class="n">{c["block"]:,}</td><td>{c["time_utc"]}</td>'
                    f'<td class="n">{_usd(c["gap_usd"])}</td><td class="n">{c["hours_before_identified"]:+.1f} h</td></tr>')
    flips = "".join(f'<tr><td>{f["to"]}</td><td class="n">{f["block"]:,}</td><td>{f["time_utc"]}</td><td>{f["postmortem_time_utc"]}</td>'
                    f'<td class="n">{f["minutes_from_postmortem"]:+.1f}</td></tr>' for f in report["pause_flips"])
    grid = []
    for s in report["scans"]:
        c = s["counts"]
        alarms = ", ".join(f'{html.escape(a["symbol"] or a["token"][:28])} {_usd(a["growth_usd"])}' for a in s["alarms"])
        cls = "bad" if s["alarms"] else "ok"
        grid.append(f'<tr><td class="n">{s["block"]:,}</td><td>{s["time_utc"][:16]}</td><td class="n">{c["backed"]}</td><td class="n">{c["standing"]}</td>'
                    f'<td class="n">{c["drift"]}</td><td class="n">{c["unverifiable"]}</td><td class="{cls}">{alarms or "none"}</td></tr>')
    src = "".join(f'<li><a href="{html.escape(s["url"])}">{html.escape(s["label"])}</a> ({s["published"]})</li>' for s in report["sources"])
    p, a = inc["peak"], inc["at_identification"]
    lead = f'{first["hours_before_identified"]:.1f} hours' if first else "n/a"
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vault Check report</title><style>{CSS}</style></head><body><main>
<h1>Two public view calls replay the NEAR Intents Oct&nbsp;1 gap, block by block</h1>
<p class="lead">ledger = <code>intents.near.mt_supply</code> (what Intents owes its users) &middot; vault = <code>v2_1.omni.hot.tg.mt_balance_of(intents.near)</code> (what it holds). Rebuilt offline from committed snapshots; data integrity {'verified' if report['manifest_ok'] else 'FAILED'}.</p>
<div class="kpis">
<div class="card kpi"><b>{_usd(p['gap_usd'])}</b><span>peak unbacked USDT, block {p['block']:,}</span></div>
<div class="card kpi"><b>{lead}</b><span>a $1,000 alarm fires before the team identified the problem (08:04 UTC)</span></div>
<div class="card kpi"><b>{_usd(a['gap_usd'])}</b><span>already unbacked at the moment of identification</span></div>
</div>
<div class="card scroll">{chart(series, incident, inc['crossings'])}</div>
<p class="lead">Log scale. Red: unbacked USDT(BSC) = ledger &minus; vault. Purple: post-mortem timeline. The gap grows in steps (mostly &times;2 between 630 and 1.3M USDT); the brief dips are blocks where a deposit had reached the vault but the ledger update and refund had not executed yet.</p>
<h2>When would an alarm have fired?</h2><div class="scroll"><table><tr><th>threshold</th><th class="n">first block</th><th>time (UTC)</th><th class="n">unbacked</th><th class="n">lead vs 08:04</th></tr>{''.join(rows)}</table></div>
<h2>The on-chain pause flag matches the post-mortem</h2><div class="scroll"><table><tr><th>flag</th><th class="n">block</th><th>on-chain time</th><th>post-mortem</th><th class="n">minutes</th></tr>{flips}</table></div>
<h2>Every fungible token, every scan</h2><p class="lead">Baseline = first scan. ALARM = an unbacked gap grew by at least $1,000 since the baseline.</p>
<div class="scroll"><table><tr><th class="n">block</th><th>time (UTC)</th><th class="n">backed</th><th class="n">standing</th><th class="n">drift</th><th class="n">unverifiable</th><th>ALARM</th></tr>{''.join(grid)}</table></div>
<h2>Sources</h2><ul>{src}</ul>
</main></body></html>"""
    with open(path, "w") as f:
        f.write(doc)
