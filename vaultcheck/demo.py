"""Write out/demo.html: a self-contained, animated replay of the October incident.

Every value on the page comes from the offline reproduction (report.json and the
incident series), so the replay shows exactly what `make reproduce` computes.
No network, no external scripts or fonts.
"""

from __future__ import annotations

import html
import json

SIM_START = "2026-09-29 12:00:00"
SIM_END = "2026-10-02 22:00:00"


def _usd(x: float) -> str:
    return f"${x:,.0f}"


def demo_data(report: dict, series: list[dict], incident: dict) -> dict:
    inc = report["incident"]
    pts = {(p["t"], p["gap_usd"]) for p in series}
    marks = [c for c in inc["crossings"] if c["block"]] + [inc["peak"], inc["at_identification"]]
    if inc["closure"]:
        marks.append(inc["closure"])
    pts |= {(m["time_utc"], m["gap_usd"]) for m in marks}
    blocks = sorted({(p["t"], p["block"]) for p in series})

    vc = []
    for c in inc["crossings"]:
        if not c["block"]:
            continue
        if c["threshold_usd"] == 0:
            text, kind = f"Gap opens: the ledger owes {_usd(c['gap_usd'])} more USDT than the vault holds. Status: DRIFT.", "drift"
        elif c["threshold_usd"] == 1000:
            text, kind = f"ALARM: the unbacked gap grew past $1,000 ({_usd(c['gap_usd'])}).", "alarm"
        else:
            text, kind = f"Unbacked gap passes {_usd(c['threshold_usd'])} ({_usd(c['gap_usd'])}).", "alarm"
        vc.append({"t": c["time_utc"], "text": text, "kind": kind, "block": c["block"]})
    p = inc["peak"]
    vc.append({"t": p["time_utc"], "kind": "alarm", "block": p["block"],
               "text": f"Peak: {_usd(p['gap_usd'])} unbacked. The vault holds {_usd(p['vault'])} against a ledger of {_usd(p['ledger'])}."})
    for f in report["pause_flips"]:
        vc.append({"t": f["time_utc"], "kind": "info", "block": f["block"],
                   "text": f"On-chain pause flag pa_is_paused(ALL) turns {'true' if f['to'] == 'paused' else 'false'}."})
    if inc["closure"]:
        c = inc["closure"]
        vc.append({"t": c["time_utc"], "kind": "ok", "block": c["block"],
                   "text": "Gap closes: the vault backs the ledger again."})

    pm = [{"t": e["time"].replace("T", " ").replace("Z", ":00")[:19], "text": e["label"], "key": e["key"]}
          for e in incident["events_utc"]]
    alarm = next(c for c in inc["crossings"] if c["threshold_usd"] == 1000)
    ident = next(e for e in pm if e["key"] == "identified")
    return {
        "start": SIM_START,
        "end": SIM_END,
        "series": sorted(pts),
        "blocks": blocks,
        "vc": sorted(vc, key=lambda e: e["t"]),
        "pm": sorted(pm, key=lambda e: e["t"]),
        "alarm": alarm["time_utc"],
        "identified": ident["t"],
        "head_start_h": alarm["hours_before_identified"],
        "peak": inc["peak"]["gap_usd"],
    }


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vault Check replay</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14171c;--muted:#5b6472;--line:#dfe3e8;--ok:#13804b;--drift:#a86400;--alarm:#c62828;--accent:#2457c5;--band:rgba(198,40,40,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1116;--panel:#161b22;--ink:#e6edf3;--muted:#9aa5b1;--line:#2b323c;--ok:#3fb27f;--drift:#e3a33b;--alarm:#ff5d5d;--accent:#6ea0ff;--band:rgba(255,93,93,.10)}}
:root[data-theme="dark"]{--bg:#0e1116;--panel:#161b22;--ink:#e6edf3;--muted:#9aa5b1;--line:#2b323c;--ok:#3fb27f;--drift:#e3a33b;--alarm:#ff5d5d;--accent:#6ea0ff;--band:rgba(255,93,93,.10)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 16px}
.stage{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.big{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:2px;white-space:nowrap}
.small{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
#status.ok{color:var(--ok)}#status.drift{color:var(--drift)}#status.alarm{color:var(--alarm)}
#gap.drift{color:var(--drift)}#gap.alarm{color:var(--alarm)}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px;margin-bottom:12px}
svg text{fill:var(--muted);font-size:12px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.cols h2{font-size:15px;margin:0 0 8px}
ol{list-style:none;margin:0;padding:0}
li{display:none;padding:6px 0 6px 10px;border-left:3px solid var(--line);margin-bottom:4px}
li.on{display:block}
li.now{background:var(--bg)}
li .tm{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
li.alarm{border-color:var(--alarm)}li.drift{border-color:var(--drift)}li.ok{border-color:var(--ok)}li.info,li.pm{border-color:var(--accent)}
.empty{color:var(--muted);font-size:13px}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:12px 0}
button{font:inherit;padding:6px 14px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
input[type=range]{flex:1;min-width:160px;accent-color:var(--accent)}
footer{color:var(--muted);font-size:13px;margin-top:20px}
code{font-size:12.5px}
.scroll{overflow-x:auto}
@media (max-width:760px){.stage{grid-template-columns:1fr 1fr}.cols{grid-template-columns:1fr}.big{font-size:20px}.scroll svg{min-width:680px}}
</style>
</head>
<body>
<main>
<h1>Vault Check: the NEAR Intents October incident, replayed from public chain state</h1>
<p class="sub">The ledger (<code>intents.near</code> <code>mt_supply</code>) against the vault (the token contract's balance of <code>intents.near</code>) for __TOKEN_LABEL__. No keys, no private data.</p>
<div class="stage">
 <div class="card"><div class="label">Time (UTC)</div><div class="big" id="clock">-</div><div class="small" id="block">-</div></div>
 <div class="card"><div class="label">Vault Check status</div><div class="big ok" id="status" aria-live="polite">BACKED</div><div class="small" id="rule">ledger &le; vault</div></div>
 <div class="card"><div class="label">Unbacked USDT</div><div class="big" id="gap">$0</div><div class="small">ledger minus vault</div></div>
 <div class="card"><div class="label">Alarm head start</div><div class="big" id="lead">-</div><div class="small" id="leadnote">alarm at $1,000 of growth</div></div>
</div>
<div class="chart"><div class="scroll">__SVG__</div></div>
<div class="controls">
 <button class="primary" id="play">Pause</button>
 <button id="restart">Restart</button>
 <button id="speed">Speed 1x</button>
 <input type="range" id="scrub" min="0" max="1000" value="0" aria-label="Replay position">
</div>
<div class="cols">
 <div class="card"><h2>What Vault Check sees (public archival RPC)</h2><ol id="vc"></ol><p class="empty" id="vc0">Nothing yet: every token is backed.</p></div>
 <div class="card"><h2>What happened (the team's post-mortem)</h2><ol id="pm"></ol><p class="empty" id="pm0">No public sign of trouble yet.</p></div>
</div>
<footer>Every number on this page is rebuilt offline by <code>make reproduce</code> from committed archival snapshots (__POINTS__ blocks, threshold crossings located to the exact block). Post-mortem times: __SOURCES__.</footer>
</main>
<script>
const D = __DATA__;
const T = s => Date.parse(s.replace(" ", "T") + "Z");
const t0 = T(D.start), t1 = T(D.end), span = t1 - t0;
const S = D.series.map(([t, g]) => [T(t), g]);
const B = D.blocks.map(([t, b]) => [T(t), b]);
const alarmT = T(D.alarm), identT = T(D.identified);
const W = 1000, L = 64, R = 16;
const DURATION = 45000;
let pos = 0, playing = true, speed = 1, last = null;
const $ = id => document.getElementById(id);
const fmtUSD = v => "$" + Math.round(v).toLocaleString("en-US");
const pad = n => String(n).padStart(2, "0");
const fmtT = ms => { const d = new Date(ms); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };
const fmtH = ms => { const m = Math.max(0, Math.round(ms / 60000)); return `${Math.floor(m / 60)} h ${pad(m % 60)} m`; };
function at(arr, t) { let lo = 0, hi = arr.length - 1, k = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m][0] <= t) { k = m; lo = m + 1; } else hi = m - 1; } return k < 0 ? null : arr[k][1]; }
function build(listId, items, cls) {
  const ol = $(listId);
  items.forEach(e => { const li = document.createElement("li"); li.className = cls ? cls : e.kind; li.dataset.t = T(e.t);
    li.innerHTML = `<div class="tm">${e.t} UTC${e.block ? " &middot; block " + e.block.toLocaleString("en-US") : ""}</div>${e.text}`; ol.appendChild(li); });
}
build("vc", D.vc); build("pm", D.pm, "pm");
function render() {
  const now = t0 + pos * span;
  const gap = at(S, now) || 0, blk = at(B, now);
  $("clock").textContent = fmtT(now);
  $("block").textContent = blk ? "block \\u2248 " + blk.toLocaleString("en-US") : "";
  const st = gap <= 0 ? "ok" : (now >= alarmT ? "alarm" : "drift");
  const sEl = $("status"); sEl.textContent = st === "ok" ? "BACKED" : st.toUpperCase(); sEl.className = "big " + st;
  $("rule").textContent = st === "ok" ? "ledger \\u2264 vault" : st === "drift" ? "gap open, growth below $1,000" : "gap grew past $1,000";
  const gEl = $("gap"); gEl.textContent = fmtUSD(gap); gEl.className = "big " + (st === "ok" ? "" : st);
  if (now < alarmT) { $("lead").textContent = "-"; $("leadnote").textContent = "alarm at $1,000 of growth"; }
  else if (now < identT) { $("lead").textContent = fmtH(now - alarmT); $("leadnote").textContent = "ringing; the team has not noticed yet"; }
  else { $("lead").textContent = fmtH(identT - alarmT); $("leadnote").textContent = "before the team identified it (" + D.identified.slice(11, 16) + " UTC)"; }
  for (const id of ["vc", "pm"]) {
    let latest = null, any = false;
    for (const li of $(id).children) { const on = +li.dataset.t <= now; li.classList.toggle("on", on); li.classList.remove("now"); if (on) { latest = li; any = true; } }
    if (latest) latest.classList.add("now");
    $(id + "0").style.display = any ? "none" : "block";
  }
  const x = L + pos * (W - L - R);
  $("clip").setAttribute("width", Math.max(0, x - L));
  $("cursor").setAttribute("x1", x); $("cursor").setAttribute("x2", x);
  for (const el of document.querySelectorAll("[data-show]")) el.style.display = now >= +T(el.dataset.show) ? "" : "none";
  $("scrub").value = Math.round(pos * 1000);
}
function tick(ts) {
  if (last !== null && playing) { pos = Math.min(1, pos + (ts - last) / DURATION * speed); if (pos >= 1) { playing = false; $("play").textContent = "Play"; } render(); }
  last = ts; requestAnimationFrame(tick);
}
$("play").onclick = () => { if (pos >= 1) pos = 0; playing = !playing; $("play").textContent = playing ? "Pause" : "Play"; };
$("restart").onclick = () => { pos = 0; playing = true; $("play").textContent = "Pause"; render(); };
$("speed").onclick = () => { speed = speed === 1 ? 2 : speed === 2 ? 4 : 1; $("speed").textContent = "Speed " + speed + "x"; };
$("scrub").oninput = e => { pos = e.target.value / 1000; playing = false; $("play").textContent = "Play"; render(); };
const q = new URLSearchParams(location.search);
if (q.has("t")) { pos = Math.max(0, Math.min(1, (T(q.get("t")) - t0) / span)); playing = false; }
if (q.get("autoplay") === "0" || matchMedia("(prefers-reduced-motion: reduce)").matches) { if (!q.has("t")) pos = 1; playing = false; }
$("play").textContent = playing ? "Pause" : "Play";
render(); requestAnimationFrame(tick);
</script>
</body>
</html>
"""


def _svg(data: dict) -> str:
    import datetime as dt
    import math

    W, H, L, R, TOP, BOT = 1000, 300, 64, 16, 14, 34
    p = lambda s: dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    t0, t1 = p(data["start"]), p(data["end"])
    span = (t1 - t0).total_seconds()
    x = lambda s: L + (p(s) - t0).total_seconds() / span * (W - L - R)
    y = lambda v: TOP + (1 - (math.log10(v) if v >= 1 else 0) / 7) * (H - TOP - BOT)

    pts = [(t, g) for t, g in data["series"] if t0 <= p(t) <= t1]
    d = []
    for i, (t, g) in enumerate(pts):  # step line: hold each value until the next snapshot
        if i:
            d.append(f"L{x(t):.1f},{y(pts[i - 1][1]):.1f}")
        d.append(f"{'M' if not i else 'L'}{x(t):.1f},{y(g):.1f}")
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Unbacked USDT over time, log scale">',
           f'<defs><clipPath id="cp"><rect id="clip" x="{L}" y="0" width="0" height="{H}"/></clipPath></defs>']
    for k in range(0, 8):
        yy = y(10 ** k)
        lab = "$0" if k == 0 else f"${10 ** k:,.0f}".replace(",000,000", "M").replace(",000", "k")
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--line)"/>'
                   f'<text x="{L - 6}" y="{yy + 4:.1f}" text-anchor="end">{lab}</text>')
    day = t0.replace(hour=0)
    while day <= t1:
        if day >= t0:
            xx = x(day.strftime("%Y-%m-%d %H:%M:%S"))
            out.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{TOP}" y2="{H - BOT}" stroke="var(--line)"/>'
                       f'<text x="{xx + 4:.1f}" y="{H - 12}">{day.strftime("%d %b")}</text>')
        day += dt.timedelta(days=1)
    ax, ix = x(data["alarm"]), x(data["identified"])
    out.append(f'<g data-show="{data["identified"]}"><rect x="{ax:.1f}" y="{TOP}" width="{ix - ax:.1f}" height="{H - TOP - BOT}" fill="var(--band)"/>'
               f'<text x="{(ax + ix) / 2:.1f}" y="{TOP + 16}" text-anchor="middle" style="fill:var(--alarm);font-weight:600">'
               f'{data["head_start_h"]:.1f} h head start</text></g>')
    out.append(f'<g data-show="{data["alarm"]}"><line x1="{ax:.1f}" x2="{ax:.1f}" y1="{TOP}" y2="{H - BOT}" stroke="var(--alarm)" stroke-dasharray="4 3"/>'
               f'<text x="{ax + 4:.1f}" y="{H - BOT - 6}" style="fill:var(--alarm)">ALARM</text></g>')
    out.append(f'<g data-show="{data["identified"]}"><line x1="{ix:.1f}" x2="{ix:.1f}" y1="{TOP}" y2="{H - BOT}" stroke="var(--ink)" stroke-dasharray="4 3"/>'
               f'<text x="{ix + 4:.1f}" y="{H - BOT - 6}" style="fill:var(--ink)">team identifies</text></g>')
    out.append(f'<path d="{" ".join(d)}" fill="none" stroke="var(--alarm)" stroke-width="2" clip-path="url(#cp)"/>')
    out.append(f'<line id="cursor" x1="{L}" x2="{L}" y1="{TOP}" y2="{H - BOT}" stroke="var(--accent)" stroke-width="1.5"/>')
    out.append("</svg>")
    return "".join(out)


def write_demo(report: dict, series: list[dict], incident: dict, path: str) -> None:
    data = demo_data(report, series, incident)
    sources = ", ".join(f'<a href="{html.escape(s["url"])}">{html.escape(s["label"])}</a>' for s in incident["sources"])
    page = (PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
            .replace("__SVG__", _svg(data))
            .replace("__TOKEN_LABEL__", html.escape(incident["token_label"]))
            .replace("__POINTS__", f'{report["incident"]["points"]:,}')
            .replace("__SOURCES__", sources))
    with open(path, "w") as f:
        f.write(page)
