"""Static site builder: renders docs/index.html, docs/player.html and JSON
payloads (including one file per active player) for GitHub Pages."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import BattedBallEvent
from .prediction import player_form

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
  a.pl { color:var(--text); text-decoration:none; border-bottom:1px dotted var(--muted); }
  a.pl:hover { color:var(--accent); border-bottom-color:var(--accent); }
  .hits { display:flex; gap:8px; flex-wrap:wrap; margin:4px 0 12px; }
  .hit-chip { background:#1e3320; border:1px solid #3f6b3c; border-radius:8px;
              padding:4px 10px; font-size:12.5px; }
  .hit-chip b { color:#9fe08c; }
  .repeat { color:var(--accent); font-weight:700; cursor:help; }
  #analysis-chart-wrap { margin:14px 0 6px; }
  #analysis-chart svg { display:block; width:100%; height:auto; }
  .chart-tip { position:fixed; z-index:10; pointer-events:none; display:none;
               background:#212c44; border:1px solid var(--line); border-radius:8px;
               padding:8px 12px; font-size:12.5px; max-width:260px;
               box-shadow:0 4px 14px rgba(0,0,0,.4); }
  .chart-tip b { color:var(--accent); }
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
    <div id="mc-hits" class="hits" hidden></div>
    <table id="likely">
      <thead><tr>
        <th class="num">#</th>
        <th>Player</th>
        <th>Team</th>
        <th class="num">Expectancy</th>
        <th class="num">Adj</th>
        <th class="num">Streak</th>
        <th>EV</th>
        <th>Parks</th>
        <th>Freq</th>
        <th class="num">Max EV 7d</th>
        <th class="num">Max dist 7d</th>
        <th class="num">Near-HR 7d</th>
        <th class="num">2B/3B</th>
        <th class="num">HR 7d</th>
        <th>Next game</th>
        <th>Band HR rate</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <p class="note">Expectancy (0–100) blends the streak of consecutive games with a
    near-HR event, how often recent games qualify, and whether EV / would-be-HR parks /
    near-HR frequency are trending up (▲ rising · ▬ flat · ▼ falling). Near-HRs that went
    for doubles/triples (2B/3B) weigh more than ones caught at the track. Max EV / Max dist
    show the hardest and farthest ball hit in the last 7 days — the "why" behind the rank.
    HR 7d is informational only (homers don't raise or lower the score). Adj multiplies
    Expectancy by the next game's weather (hot and wind blowing out boost, wind blowing in
    and cold drag, domes and missing forecasts change nothing) — rows rank by Adj, and
    "Next game" shows the weather behind it. 💥 chips are the
    model checking itself: players flagged on a recent pull who have since homered.
    ↻ next to a name means the player was also flagged on the previous pull and has kept
    producing. "Band HR rate" is
    measured from this tracker's own history: how often players scoring in the same range
    homered soon after; until a range has enough samples it shows how many it has
    collected so far.</p>
  </section>

  <section id="consistency-section" hidden>
    <h2>Consistency leaderboard</h2>
    <p class="note">Players currently on a run of consecutive prediction pulls — they
    keep re-qualifying for "Most likely to homer" pull after pull, not just today.
    Pull streak = consecutive daily pulls (ending today) the player has appeared on;
    Game streak = consecutive qualifying game-days feeding today's score.</p>
    <table id="consistency">
      <thead><tr>
        <th class="num">#</th>
        <th>Player</th>
        <th>Team</th>
        <th class="num">Pull streak</th>
        <th class="num">Total flags</th>
        <th class="num">Avg score</th>
        <th class="num">Current score</th>
        <th class="num">Game streak</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </section>

  <section id="analysis-section" hidden>
    <h2>Today's read</h2>
    <div id="analysis-chart-wrap" hidden>
      <div class="sub" id="analysis-chart-title"></div>
      <div id="analysis-chart"></div>
    </div>
    <div id="analysis-text"></div>
    <p class="note" id="analysis-meta"></p>
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
        <th class="num" data-k="temp_f">Wx</th>
        <th>Flags</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <p class="note">Flags: <b>DIST</b> = non-HR &gt; distance threshold · <b>PARKS</b> = would have
    left ≥ min parks (park-adjusted count from Baseball Savant) · <b>BRL</b> = composite
    barrel-proximity score over threshold. "HR parks" is Savant's park-adjusted count of
    stadiums (of 30) where that ball is a home run. Wx is the game's weather:
    temp, wind mph and direction (↑out = blowing out, ↓in = blowing in).</p>
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
function tdPlayer(name, id) {
  const c = document.createElement("td");
  const a = document.createElement("a");
  a.className = "pl";
  a.href = "player.html?id=" + id;
  a.textContent = name;
  c.append(a);
  return c;
}
const WIND_GLYPH = { out: "↑out", in: "↓in", cross: "↔", none: "calm", varies: "~" };
function wxText(temp, mph, dir, cond) {
  if (cond === "Dome" || cond === "Roof Closed") return cond;
  if (temp === null || temp === undefined) return "—";
  let s = Math.round(temp) + "°";
  if (mph && WIND_GLYPH[dir]) s += " " + Math.round(mph) + " " + WIND_GLYPH[dir];
  return s;
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
    tr.append(tdPlayer(e.player_name, e.player_id), td(e.team), td(e.opponent), td(e.result),
      td(e.exit_velocity, 1), td(e.launch_angle, 1), td(e.hit_distance, 1),
      td(e.would_be_hr_count, 1), td(e.barrel_score, 1));
    const wxc = td(wxText(e.temp_f, e.wind_mph, e.wind_dir, e.weather_condition), 1);
    if (e.weather_condition) wxc.title = e.weather_condition +
      (e.venue_name ? " · " + e.venue_name : "");
    tr.append(wxc);
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
    .map(p => ({ player_id: p.player_id, player_name: p.player_name, team: p.team,
                 heating_up: p.heating_up, ...p.windows[w] }))
    .filter(r => r.near_hr_any > 0 || r.hr > 0)
    .filter(r => (!team || r.team === team) && (!hotOnly || r.heating_up));
  rows.sort((a, b) => cmp(a, b, state.trSort.k, state.trSort.dir));
  const body = document.querySelector("#trends tbody");
  body.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.append(tdPlayer(r.player_name, r.player_id), td(r.team), td(r.near_hr_any, 1),
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

const BAR = "#b8842a";  // validated for the dark surface (lightness band + 3:1)
function renderExpectancyChart() {
  const p = state.predictions;
  if (!p || !p.players || p.players.length === 0) return;
  const rows = p.players;
  document.getElementById("analysis-chart-wrap").hidden = false;
  document.getElementById("analysis-chart-title").textContent =
    `Weather-adjusted expectancy — today's ${rows.length} selections (0–100)`;

  const NS = "http://www.w3.org/2000/svg";
  const holder = document.getElementById("analysis-chart");
  holder.innerHTML = "";
  const W = Math.min(Math.max(holder.clientWidth || 720, 420), 900);
  const rowH = 26, barH = 12, labelW = 168, valueW = 44, top = 6;
  const plotW = W - labelW - valueW;
  const H = top + rows.length * rowH + 18;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Horizontal bar chart of expectancy scores for today's selections");
  const x = (v) => labelW + (v / 100) * plotW;

  // Recessive hairline gridlines; values are all tip-labeled so no tick text.
  for (const g of [25, 50, 75, 100]) {
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", x(g)); line.setAttribute("x2", x(g));
    line.setAttribute("y1", top);  line.setAttribute("y2", top + rows.length * rowH);
    line.setAttribute("stroke", "#2a3550"); line.setAttribute("stroke-width", "1");
    svg.append(line);
  }

  const tip = document.createElement("div");
  tip.className = "chart-tip";
  document.body.append(tip);

  rows.forEach((r, i) => {
    const y = top + i * rowH, yMid = y + rowH / 2;

    const name = document.createElementNS(NS, "text");
    name.setAttribute("x", labelW - 10); name.setAttribute("y", yMid + 4);
    name.setAttribute("text-anchor", "end");
    name.setAttribute("fill", "#e8ecf4"); name.setAttribute("font-size", "12.5");
    name.textContent = (r.repeat ? "↻ " : "") + r.player_name;
    svg.append(name);

    // Bar: square at the baseline, 4px rounded data-end.
    const score = (r.adjusted_score === null || r.adjusted_score === undefined)
      ? r.expectancy_score : r.adjusted_score;
    const w = Math.max((Math.min(score, 100) / 100) * plotW, 2);
    const rr = Math.min(4, w);
    const bar = document.createElementNS(NS, "path");
    bar.setAttribute("d",
      `M${labelW},${yMid - barH / 2} h${w - rr} a${rr},${rr} 0 0 1 ${rr},${rr}` +
      ` v${barH - 2 * rr} a${rr},${rr} 0 0 1 ${-rr},${rr} h${-(w - rr)} Z`);
    bar.setAttribute("fill", BAR);
    svg.append(bar);

    const val = document.createElementNS(NS, "text");
    val.setAttribute("x", labelW + w + 8); val.setAttribute("y", yMid + 4);
    val.setAttribute("fill", "#e8ecf4"); val.setAttribute("font-size", "12");
    val.setAttribute("font-variant-numeric", "tabular-nums");
    val.textContent = score;
    svg.append(val);

    // Full-row hover target (bigger than the mark) with an HTML tooltip.
    const hit = document.createElementNS(NS, "rect");
    hit.setAttribute("x", 0); hit.setAttribute("y", y);
    hit.setAttribute("width", W); hit.setAttribute("height", rowH);
    hit.setAttribute("fill", "transparent");
    hit.addEventListener("mousemove", (ev) => {
      tip.innerHTML = `<b>${r.player_name}</b> (${r.team})<br>` +
        `Expectancy ${r.expectancy_score} · streak ${r.streak}` +
        ` · ${r.near_hr_7d} near-HR / 7d<br>` +
        `Max EV ${r.max_ev_7d} mph · max dist ${r.max_distance_7d} ft` +
        (r.hr_7d ? `<br>${r.hr_7d} HR this week` : "") +
        (r.game_weather ? `<br>Next: ${wxText(r.game_weather.temp_f,
          r.game_weather.wind_mph, r.game_weather.wind_dir,
          r.game_weather.weather_condition)} · weather ×${r.weather_factor}` : "");
      tip.style.display = "block";
      tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - 280) + "px";
      tip.style.top = (ev.clientY + 14) + "px";
    });
    hit.addEventListener("mouseleave", () => { tip.style.display = "none"; });
    svg.append(hit);
  });

  const axis = document.createElementNS(NS, "text");
  axis.setAttribute("x", x(100)); axis.setAttribute("y", top + rows.length * rowH + 14);
  axis.setAttribute("text-anchor", "end");
  axis.setAttribute("fill", "#8fa0bd"); axis.setAttribute("font-size", "11");
  axis.textContent = "100";
  svg.append(axis);
  holder.append(svg);
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
  const hitsDiv = document.getElementById("mc-hits");
  hitsDiv.innerHTML = "";
  if (p.recent_hits && p.recent_hits.length) {
    hitsDiv.hidden = false;
    for (const h of p.recent_hits) {
      const chip = document.createElement("span");
      chip.className = "hit-chip";
      chip.innerHTML = `💥 <b>${h.player_name}</b> (${h.team}) — flagged ` +
        `${h.flagged_on} at ${h.flagged_score} → ` +
        `${h.hr_count > 1 ? h.hr_count + " HR" : "HR"} on ${h.hr_on}`;
      hitsDiv.append(chip);
    }
  }
  const body = document.querySelector("#likely tbody");
  body.innerHTML = "";
  p.players.forEach((r, i) => {
    const tr = document.createElement("tr");
    const nameCell = tdPlayer(r.player_name, r.player_id);
    if (r.repeat) {
      const badge = document.createElement("span");
      badge.className = "repeat";
      badge.title = "Also flagged on the previous pull — qualified again";
      badge.textContent = " ↻";
      nameCell.append(badge);
    }
    const adj = (r.adjusted_score === null || r.adjusted_score === undefined)
      ? r.expectancy_score : r.adjusted_score;
    const adjCell = td(adj, 1);
    if (r.weather_factor && r.weather_factor !== 1)
      adjCell.title = "weather ×" + r.weather_factor;
    tr.append(td(i + 1, 1), nameCell, td(r.team),
      td(r.expectancy_score, 1), adjCell,
      td(r.streak ? r.streak + (r.streak > 1 ? " games" : " game") : "—", 1));
    for (const k of ["max_ev", "parks_sum", "near_hr"]) {
      const c = document.createElement("td");
      c.innerHTML = arrow(r.slopes[k]);
      tr.append(c);
    }
    const gw = r.game_weather;
    const gwCell = td(gw
      ? wxText(gw.temp_f, gw.wind_mph, gw.wind_dir, gw.weather_condition) : "—");
    if (gw) gwCell.title = [gw.venue_name, gw.weather_condition,
      r.weather_factor ? "factor ×" + r.weather_factor : ""]
      .filter(Boolean).join(" · ");
    tr.append(td(r.max_ev_7d, 1), td(r.max_distance_7d, 1),
      td(r.near_hr_7d, 1), td(r.near_hr_xbh_7d, 1), td(r.hr_7d, 1), gwCell,
      td(r.band_rate !== null
        ? Math.round(r.band_rate * 100) + "% (n=" + r.band_samples + ")"
        : "collecting: " + r.band_samples + "/" + p.min_samples + " samples"));
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
function renderConsistency() {
  const c = state.consistency;
  if (!c || !c.players || c.players.length === 0) return;
  document.getElementById("consistency-section").hidden = false;
  const body = document.querySelector("#consistency tbody");
  body.innerHTML = "";
  c.players.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.append(td(i + 1, 1), tdPlayer(r.player_name, r.player_id), td(r.team),
      td(r.record_streak, 1), td(r.total_flags, 1), td(r.avg_score, 1),
      td(r.current_score, 1), td(r.game_streak, 1));
    body.append(tr);
  });
}

async function init() {
  const [meta, latest, trends, predictions, consistency, analysis] = await Promise.all([
    fetch("data/meta.json" + bust).then(r => r.json()),
    fetch("data/latest.json" + bust).then(r => r.json()),
    fetch("data/trends.json" + bust).then(r => r.json()),
    fetch("data/predictions.json" + bust)
      .then(r => r.ok ? r.json() : null).catch(() => null),
    fetch("data/consistency.json" + bust)
      .then(r => r.ok ? r.json() : null).catch(() => null),
    fetch("data/analysis.json" + bust)
      .then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  document.getElementById("meta").textContent =
    `Data through ${meta.latest_date} · ${meta.games_processed} games, ` +
    `${meta.total_events} batted balls, ${meta.near_hr_events} near-HR` +
    (meta.home_runs !== undefined ? `, ${meta.home_runs} HR` : "") +
    ` · generated ${new Date(meta.generated_at).toLocaleString()}`;
  document.getElementById("latest-date").textContent = latest.date;

  state.events = latest.events;
  state.trends = trends;
  state.predictions = predictions;
  state.consistency = consistency;
  renderConsistency();


  // "Today's read" — expectancy chart (always current, from predictions)
  // plus the LLM-written blurb, which shows only while it matches the data.
  const freshBlurb = analysis && analysis.text && analysis.as_of === meta.latest_date;
  const haveSelections = predictions && predictions.players && predictions.players.length;
  if (freshBlurb || haveSelections) {
    document.getElementById("analysis-section").hidden = false;
    if (haveSelections) renderExpectancyChart();
  }
  if (freshBlurb) {
    const box = document.getElementById("analysis-text");
    for (const para of String(analysis.text).split(/\n{2,}/)) {
      const el = document.createElement("p");
      el.textContent = para.trim();
      box.append(el);
    }
    document.getElementById("analysis-meta").textContent =
      `Written by ${analysis.model || "an LLM"} · ${analysis.as_of}` +
      ` · commentary, not part of the scoring`;
  }

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


PLAYER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Player — __TITLE__</title>
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
  table { border-collapse:collapse; width:100%; background:var(--panel);
          border-radius:8px; overflow:hidden; font-size:13.5px; }
  th, td { padding:7px 10px; text-align:left; border-bottom:1px solid var(--line); }
  th { color:var(--muted); white-space:nowrap; }
  tr:hover td { background:#212c44; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .flag { display:inline-block; padding:0 6px; border-radius:10px; font-size:11.5px;
          background:#2a3550; color:var(--muted); margin-right:3px; }
  .flag.on { background:var(--accent); color:#1a1405; font-weight:600; }
  .flag.hr { background:var(--hot); color:#fff; font-weight:600; }
  .stats { display:flex; gap:12px; flex-wrap:wrap; margin:14px 0 4px; }
  .stat { background:var(--panel); border:1px solid var(--line); border-radius:8px;
          padding:10px 16px; min-width:110px; }
  .stat .v { font-size:22px; font-weight:700; }
  .stat .l { font-size:11.5px; color:var(--muted); }
  a.back { color:var(--accent); text-decoration:none; font-size:13px; }
  .note { font-size:12px; color:var(--muted); margin-top:8px; }
</style>
</head>
<body>
<header>
  <a class="back" href="index.html">← back to dashboard</a>
  <h1 id="p-name">Loading…</h1>
  <div class="sub" id="p-sub"></div>
  <div class="stats" id="p-stats"></div>
</header>
<main>
  <section>
    <h2>Day by day</h2>
    <table id="p-days">
      <thead><tr>
        <th>Date</th>
        <th class="num">Batted balls</th>
        <th class="num">Near-HR</th>
        <th class="num">2B/3B near-HR</th>
        <th class="num">HR</th>
        <th class="num">Max EV</th>
        <th class="num">Max dist</th>
        <th class="num">Σ HR parks</th>
        <th class="num">Best barrel</th>
        <th class="num">Wx</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </section>
  <section>
    <h2>Batted balls (last 30 days)</h2>
    <table id="p-events">
      <thead><tr>
        <th>Date</th>
        <th>Result</th>
        <th class="num">EV (mph)</th>
        <th class="num">LA (°)</th>
        <th class="num">Dist (ft)</th>
        <th class="num">HR parks</th>
        <th class="num">Barrel score</th>
        <th>Flags</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <p class="note">Every tracked batted ball, newest first. Highlighted flags are the
    near-HR definitions this ball met; HR marks actual home runs. These are the results
    behind the player's expectancy score and trend rank.</p>
  </section>
</main>
<script>
const bust = "?v=" + Date.now();
function td(v, num) {
  const c = document.createElement("td");
  if (num) c.className = "num";
  c.textContent = (v === null || v === undefined) ? "—" : v;
  return c;
}
const WIND_GLYPH = { out: "↑out", in: "↓in", cross: "↔", none: "calm", varies: "~" };
function wxText(temp, mph, dir, cond) {
  if (cond === "Dome" || cond === "Roof Closed") return cond;
  if (temp === null || temp === undefined) return "—";
  let s = Math.round(temp) + "°";
  if (mph && WIND_GLYPH[dir]) s += " " + Math.round(mph) + " " + WIND_GLYPH[dir];
  return s;
}
function stat(label, value) {
  const d = document.createElement("div");
  d.className = "stat";
  d.innerHTML = `<div class="v">${value}</div><div class="l">${label}</div>`;
  return d;
}
async function init() {
  const id = new URLSearchParams(location.search).get("id");
  if (!id) throw new Error("no player id in URL");
  const p = await fetch(`data/players/${encodeURIComponent(id)}.json` + bust)
    .then(r => { if (!r.ok) throw new Error("no data for player " + id); return r.json(); });

  document.title = p.player_name + " — HR proximity";
  document.getElementById("p-name").textContent = p.player_name;
  document.getElementById("p-sub").textContent =
    `${p.team} · data through ${p.as_of}`;

  const stats = document.getElementById("p-stats");
  if (p.form) {
    stats.append(
      stat("Expectancy", p.form.expectancy_score),
      stat("Streak", p.form.streak + (p.form.streak === 1 ? " game" : " games")),
      stat("Qualifying rate", Math.round(p.form.frequency * 100) + "%"),
      stat("EV slope", p.form.slopes.max_ev),
      stat("Parks slope", p.form.slopes.parks_sum));
  }

  const dbody = document.querySelector("#p-days tbody");
  for (const d of p.days) {
    const tr = document.createElement("tr");
    tr.append(td(d.date), td(d.bbe, 1), td(d.near_hr_any, 1),
      td(d.near_hr_xbh, 1), td(d.hr, 1), td(d.max_ev, 1),
      td(d.max_distance, 1), td(d.would_be_hr_parks_sum, 1),
      td(d.max_barrel_score, 1),
      td(wxText(d.temp_f, d.wind_mph, d.wind_dir, d.weather_condition), 1));
    dbody.append(tr);
  }

  const ebody = document.querySelector("#p-events tbody");
  for (const e of p.events) {
    const tr = document.createElement("tr");
    tr.append(td(e.date), td(e.result), td(e.exit_velocity, 1),
      td(e.launch_angle, 1), td(e.hit_distance, 1),
      td(e.would_be_hr_count, 1), td(e.barrel_score, 1));
    const flags = document.createElement("td");
    if (e.result === "Home Run") {
      const s = document.createElement("span");
      s.className = "flag hr";
      s.textContent = "HR";
      flags.append(s);
    }
    for (const [label, on] of [["DIST", e.distance_flag],
        ["PARKS", e.would_be_hr_flag], ["BRL", e.barrel_flag]]) {
      const s = document.createElement("span");
      s.className = "flag" + (on ? " on" : "");
      s.textContent = label;
      flags.append(s);
    }
    tr.append(flags);
    ebody.append(tr);
  }
}
init().catch(err => {
  document.getElementById("p-name").textContent = "Player not found";
  document.getElementById("p-sub").textContent = String(err);
});
</script>
</body>
</html>
"""


def _write_player_pages(out: Path, store: Any, as_of: str,
                        config: dict[str, Any]) -> int:
    """One JSON per player active in the trends window: their day-by-day
    rollup, current form, and every tracked batted ball."""
    window = max(config["trends"]["windows"])
    start = (date_cls.fromisoformat(as_of)
             - timedelta(days=window - 1)).isoformat()
    by_player: dict[int, list[BattedBallEvent]] = defaultdict(list)
    for e in store.read_range(start, as_of):
        by_player[e.player_id].append(e)
    player_days = store.read_player_days()

    pdir = out / "data" / "players"
    pdir.mkdir(parents=True, exist_ok=True)
    for pid, evs in by_player.items():
        latest = max(evs, key=lambda e: e.date)
        days = {d: v for d, v in
                player_days.get(str(pid), {}).get("days", {}).items()
                if start <= d <= as_of}
        evs.sort(key=lambda e: (e.date, e.barrel_score), reverse=True)
        payload = {
            "player_id": pid,
            "player_name": latest.player_name,
            "team": latest.team,
            "as_of": as_of,
            "form": player_form(days, as_of, config) if days else None,
            "days": [{"date": d, **days[d]} for d in sorted(days, reverse=True)],
            "events": [e.to_dict() for e in evs],
        }
        (pdir / f"{pid}.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")
    return len(by_player)


def build_site(events: list[BattedBallEvent], trends: dict[str, Any],
               date: str, ingest_summary: dict[str, Any],
               config: dict[str, Any],
               predictions: dict[str, Any] | None = None,
               hit_rate: dict[str, Any] | None = None,
               recent_hits: list[dict[str, Any]] | None = None,
               consistency: list[dict[str, Any]] | None = None,
               weather_corr: dict[str, Any] | None = None,
               store: Any | None = None) -> Path:
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
        "home_runs": sum(1 for e in events if e.is_home_run),
    }
    (data_dir / "latest.json").write_text(json.dumps(latest, indent=1), encoding="utf-8")
    (data_dir / "trends.json").write_text(json.dumps(trends, indent=1), encoding="utf-8")
    (data_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if predictions is not None:
        payload = {**predictions, "hit_rate": hit_rate,
                   "recent_hits": recent_hits or []}
        (data_dir / "predictions.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")
    (data_dir / "consistency.json").write_text(
        json.dumps({"as_of": date, "players": consistency or []}, indent=1),
        encoding="utf-8")
    if weather_corr is not None:
        (data_dir / "weather.json").write_text(
            json.dumps(weather_corr, indent=1), encoding="utf-8")

    if store is not None:
        n = _write_player_pages(out, store, date, config)
        (out / "player.html").write_text(
            PLAYER_HTML.replace("__TITLE__", config["site"]["title"]),
            encoding="utf-8")
        print(f"[site] wrote {n} player pages", file=sys.stderr)

    html = INDEX_HTML.replace("__TITLE__", config["site"]["title"])
    index = out / "index.html"
    index.write_text(html, encoding="utf-8")
    return index
