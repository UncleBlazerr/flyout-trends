"""Static site builder: renders docs/index.html + JSON payloads for GitHub Pages."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import BattedBallEvent

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#0f1420; --panel:#1a2233; --text:#e8ecf4; --muted:#8fa0bd;
          --accent:#f4b942; --hot:#ff6b57; --line:#2a3550; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.5 system-ui, "Segoe UI", sans-serif; }
  header { padding:24px 28px 8px; }
  h1 { margin:0 0 4px; font-size:26px; }
  .sub { color:var(--muted); font-size:13px; }
  main { padding:12px 28px 60px; max-width:1280px; }
  section { margin-top:28px; }
  h2 { font-size:18px; border-bottom:1px solid var(--line); padding-bottom:6px; }
  .controls { display:flex; gap:12px; flex-wrap:wrap; margin:10px 0 14px;
              align-items:center; font-size:13px; color:var(--muted); }
  select, input { background:var(--panel); color:var(--text);
                  border:1px solid var(--line); border-radius:6px; padding:5px 8px; }
  table { border-collapse:collapse; width:100%; background:var(--panel);
          border-radius:8px; overflow:hidden; font-size:13.5px; }
  th, td { padding:7px 10px; text-align:left; border-bottom:1px solid var(--line); }
  th { cursor:pointer; user-select:none; color:var(--muted); white-space:nowrap;
       position:sticky; top:0; background:var(--panel); }
  th .arrow { color:var(--accent); }
  tr:hover td { background:#212c44; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .flag { display:inline-block; padding:0 6px; border-radius:10px; font-size:11.5px;
          background:#2a3550; color:var(--muted); margin-right:3px; }
  .flag.on { background:var(--accent); color:#1a1405; font-weight:600; }
  .hot { color:var(--hot); font-weight:700; }
  .note { font-size:12px; color:var(--muted); margin-top:8px; }
  .empty { color:var(--muted); padding:14px; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub" id="meta">Loading…</div>
</header>
<main>
  <section id="likely-section" hidden>
    <h2>Most likely to homer</h2>
    <div class="controls">
      <span id="ml-hitrate"></span>
    </div>
    <table id="likely">
      <thead><tr>
        <th class="num">#</th>
        <th>Player</th>
        <th>Team</th>
        <th class="num">Expectancy</th>
        <th class="num">Streak</th>
        <th>EV</th>
        <th>Parks</th>
        <th>Freq</th>
        <th class="num">Near-HR 7d</th>
        <th>Band HR rate</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <p class="note">Expectancy (0–100) blends the streak of consecutive games with a
    near-HR event, how often recent games qualify, and whether EV / would-be-HR parks /
    near-HR frequency are trending up (▲ rising · ▬ flat · ▼ falling). "Band HR rate" is
    measured from this tracker's own history: how often players scoring in the same range
    homered soon after (shown once enough samples exist).</p>
  </section>

  <section>
    <h2>Near-HR events — <span id="latest-date"></span></h2>
    <div class="controls">
      <label>Team <select id="ev-team"><option value="">All</option></select></label>
      <label>Min barrel score <input id="ev-min" type="number" value="0" min="0" max="100" step="5" style="width:70px"></label>
      <span id="ev-count"></span>
    </div>
    <table id="events">
      <thead><tr>
        <th data-k="player_name">Player</th>
        <th data-k="team">Team</th>
        <th data-k="opponent">Opp</th>
        <th data-k="result">Result</th>
        <th class="num" data-k="exit_velocity">EV (mph)</th>
        <th class="num" data-k="launch_angle">LA (°)</th>
        <th class="num" data-k="hit_distance">Dist (ft)</th>
        <th class="num" data-k="would_be_hr_count">HR parks</th>
        <th class="num" data-k="barrel_score">Barrel score</th>
        <th>Flags</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <p class="note">Flags: <b>DIST</b> = non-HR &gt; distance threshold · <b>PARKS</b> = would have
    left ≥ min parks (park-adjusted count from Baseball Savant) · <b>BRL</b> = composite
    barrel-proximity score over threshold. "HR parks" is Savant's park-adjusted count of
    stadiums (of 30) where that ball is a home run.</p>
  </section>

  <section>
    <h2>Trending players (rolling windows)</h2>
    <div class="controls">
      <label>Window <select id="tr-window"></select></label>
      <label>Team <select id="tr-team"><option value="">All</option></select></label>
      <label><input id="tr-hot" type="checkbox"> Heating up only</label>
      <span id="tr-count"></span>
    </div>
    <table id="trends">
      <thead><tr>
        <th data-k="player_name">Player</th>
        <th data-k="team">Team</th>
        <th class="num" data-k="near_hr_any">Near-HR (any)</th>
        <th class="num" data-k="near_hr_distance">By dist</th>
        <th class="num" data-k="near_hr_parks">By parks</th>
        <th class="num" data-k="near_hr_barrel">By barrel</th>
        <th class="num" data-k="hr">HR</th>
        <th class="num" data-k="max_ev_near_hr">Max EV</th>
        <th class="num" data-k="avg_ev_near_hr">Avg EV</th>
        <th class="num" data-k="would_be_hr_parks_sum">Σ HR parks</th>
        <th class="num" data-k="parks_slope">Slope</th>
        <th data-k="trend_direction">Trend</th>
        <th data-k="heating_up">🔥</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <p class="note">EV columns are over near-HR events only. Slope = daily
    would-be-HR-parks trend within the window; 🔥 = enough recent near-HR events with a
    rising slope.</p>
  </section>
</main>
<script>
const bust = "?v=" + Date.now();
const state = { events: [], trends: null, predictions: null,
  evSort: {k:"barrel_score", dir:-1}, trSort: {k:"near_hr_any", dir:-1} };

function td(v, num) {
  const c = document.createElement("td");
  if (num) c.className = "num";
  c.textContent = (v === null || v === undefined) ? "—" : v;
  return c;
}
function cmp(a, b, k, dir) {
  const x = a[k], y = b[k];
  if (x === y) return 0;
  if (x === null || x === undefined) return 1;
  if (y === null || y === undefined) return -1;
  return (x < y ? -1 : 1) * dir;
}
function wireSort(tableId, sortState, render) {
  document.querySelectorAll(`#${tableId} th[data-k]`).forEach(th => {
    th.addEventListener("click", () => {
      const k = th.dataset.k;
      sortState.dir = (sortState.k === k) ? -sortState.dir : -1;
      sortState.k = k;
      render();
    });
  });
}
function markSort(tableId, sortState) {
  document.querySelectorAll(`#${tableId} th[data-k]`).forEach(th => {
    const base = th.textContent.replace(/ [▲▼]$/, "");
    th.innerHTML = base + (th.dataset.k === sortState.k
      ? ` <span class="arrow">${sortState.dir < 0 ? "▼" : "▲"}</span>` : "");
  });
}

function renderEvents() {
  const team = document.getElementById("ev-team").value;
  const min = Number(document.getElementById("ev-min").value) || 0;
  let rows = state.events.filter(e =>
    (!team || e.team === team) && e.barrel_score >= min);
  rows.sort((a, b) => cmp(a, b, state.evSort.k, state.evSort.dir));
  const body = document.querySelector("#events tbody");
  body.innerHTML = "";
  for (const e of rows) {
    const tr = document.createElement("tr");
    tr.append(td(e.player_name), td(e.team), td(e.opponent), td(e.result),
      td(e.exit_velocity, 1), td(e.launch_angle, 1), td(e.hit_distance, 1),
      td(e.would_be_hr_count, 1), td(e.barrel_score, 1));
    const flags = document.createElement("td");
    for (const [label, on] of [["DIST", e.distance_flag],
        ["PARKS", e.would_be_hr_flag], ["BRL", e.barrel_flag]]) {
      const s = document.createElement("span");
      s.className = "flag" + (on ? " on" : "");
      s.textContent = label;
      flags.append(s);
    }
    tr.append(flags);
    body.append(tr);
  }
  document.getElementById("ev-count").textContent = rows.length + " events";
  markSort("events", state.evSort);
}

function renderTrends() {
  if (!state.trends) return;
  const w = document.getElementById("tr-window").value;
  const team = document.getElementById("tr-team").value;
  const hotOnly = document.getElementById("tr-hot").checked;
  let rows = state.trends.players
    .map(p => ({ player_name: p.player_name, team: p.team,
                 heating_up: p.heating_up, ...p.windows[w] }))
    .filter(r => r.near_hr_any > 0 || r.hr > 0)
    .filter(r => (!team || r.team === team) && (!hotOnly || r.heating_up));
  rows.sort((a, b) => cmp(a, b, state.trSort.k, state.trSort.dir));
  const body = document.querySelector("#trends tbody");
  body.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.append(td(r.player_name), td(r.team), td(r.near_hr_any, 1),
      td(r.near_hr_distance, 1), td(r.near_hr_parks, 1), td(r.near_hr_barrel, 1),
      td(r.hr, 1), td(r.max_ev_near_hr, 1), td(r.avg_ev_near_hr, 1),
      td(r.would_be_hr_parks_sum, 1), td(r.parks_slope, 1), td(r.trend_direction));
    const hot = document.createElement("td");
    hot.innerHTML = r.heating_up ? '<span class="hot">🔥</span>' : "";
    tr.append(hot);
    body.append(tr);
  }
  document.getElementById("tr-count").textContent = rows.length + " players";
  markSort("trends", state.trSort);
}

function arrow(slope) {
  const EPS = 0.01;
  if (slope > EPS) return '<span class="hot">▲</span>';
  if (slope < -EPS) return "▼";
  return "▬";
}
function renderLikely() {
  const p = state.predictions;
  if (!p || !p.players || p.players.length === 0) return;
  document.getElementById("likely-section").hidden = false;
  const hr = p.hit_rate;
  document.getElementById("ml-hitrate").textContent = hr && hr.overall.flagged
    ? `Track record: ${hr.overall.hr_followed}/${hr.overall.flagged} flagged players ` +
      `homered within ${hr.horizon_days} days (${Math.round(hr.overall.rate * 100)}%) ` +
      `across ${hr.resolved_records} resolved days`
    : "Track record: accumulating — prediction receipts resolve after " +
      p.horizon_days + " days";
  const body = document.querySelector("#likely tbody");
  body.innerHTML = "";
  p.players.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.append(td(i + 1, 1), td(r.player_name), td(r.team),
      td(r.expectancy_score, 1),
      td(r.streak ? r.streak + (r.streak > 1 ? " games" : " game") : "—", 1));
    for (const k of ["max_ev", "parks_sum", "near_hr"]) {
      const c = document.createElement("td");
      c.innerHTML = arrow(r.slopes[k]);
      tr.append(c);
    }
    tr.append(td(r.near_hr_7d, 1),
      td(r.band_rate !== null
        ? Math.round(r.band_rate * 100) + "% (n=" + r.band_samples + ")"
        : "— (n=" + r.band_samples + ")"));
    body.append(tr);
  });
}

function fillTeams(selectId, teams) {
  const sel = document.getElementById(selectId);
  for (const t of teams) {
    const o = document.createElement("option");
    o.value = o.textContent = t;
    sel.append(o);
  }
}

async function init() {
  const [meta, latest, trends, predictions] = await Promise.all([
    fetch("data/meta.json" + bust).then(r => r.json()),
    fetch("data/latest.json" + bust).then(r => r.json()),
    fetch("data/trends.json" + bust).then(r => r.json()),
    fetch("data/predictions.json" + bust)
      .then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  document.getElementById("meta").textContent =
    `Data through ${meta.latest_date} · ${meta.games_processed} games, ` +
    `${meta.total_events} batted balls, ${meta.near_hr_events} near-HR · ` +
    `generated ${new Date(meta.generated_at).toLocaleString()}`;
  document.getElementById("latest-date").textContent = latest.date;

  state.events = latest.events;
  state.trends = trends;
  state.predictions = predictions;

  fillTeams("ev-team", [...new Set(latest.events.map(e => e.team))].sort());
  fillTeams("tr-team", [...new Set(trends.players.map(p => p.team))].sort());
  const wSel = document.getElementById("tr-window");
  for (const w of trends.windows) {
    const o = document.createElement("option");
    o.value = w; o.textContent = w + " days";
    wSel.append(o);
  }
  document.getElementById("ev-team").addEventListener("change", renderEvents);
  document.getElementById("ev-min").addEventListener("input", renderEvents);
  document.getElementById("tr-window").addEventListener("change", renderTrends);
  document.getElementById("tr-team").addEventListener("change", renderTrends);
  document.getElementById("tr-hot").addEventListener("change", renderTrends);
  wireSort("events", state.evSort, renderEvents);
  wireSort("trends", state.trSort, renderTrends);
  renderLikely();
  renderEvents();
  renderTrends();
}
init().catch(err => {
  document.getElementById("meta").textContent = "Failed to load data: " + err;
});
</script>
</body>
</html>
"""


def build_site(events: list[BattedBallEvent], trends: dict[str, Any],
               date: str, ingest_summary: dict[str, Any],
               config: dict[str, Any],
               predictions: dict[str, Any] | None = None,
               hit_rate: dict[str, Any] | None = None) -> Path:
    """Write index.html + data JSON into the GitHub Pages source dir (docs/)."""
    out = Path(config["site"]["output_dir"])
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    near_hr = sorted((e for e in events if e.is_near_hr),
                     key=lambda e: e.barrel_score, reverse=True)
    latest = {"date": date, "events": [e.to_dict() for e in near_hr]}
    meta = {
        "latest_date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games_processed": ingest_summary.get("games_processed", 0),
        "games_skipped_not_final": ingest_summary.get("games_skipped_not_final", []),
        "total_events": len(events),
        "near_hr_events": len(near_hr),
    }
    (data_dir / "latest.json").write_text(json.dumps(latest, indent=1), encoding="utf-8")
    (data_dir / "trends.json").write_text(json.dumps(trends, indent=1), encoding="utf-8")
    (data_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if predictions is not None:
        payload = {**predictions, "hit_rate": hit_rate}
        (data_dir / "predictions.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")

    html = INDEX_HTML.replace("__TITLE__", config["site"]["title"])
    index = out / "index.html"
    index.write_text(html, encoding="utf-8")
    return index
