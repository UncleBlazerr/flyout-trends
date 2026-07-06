// Page smoke test: load the built dashboard in jsdom against the local server
// and assert both tables render rows with real data. Run:
//   python -m http.server 8123 -d docs   (in background)
//   node tests/page_smoke.mjs
import { createRequire } from "module";
const require = createRequire("file:///" + process.env.TEMP.replace(/\\/g, "/") + "/hrtracker-pagetest/x.js");
const { JSDOM } = require("jsdom");

const BASE = "http://localhost:8123/";
const dom = await JSDOM.fromURL(BASE, {
  resources: "usable",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  beforeParse(window) {
    // jsdom has no fetch; bridge to Node's, resolving page-relative URLs.
    window.fetch = (url, opts) => fetch(new URL(url, BASE).href, opts);
  },
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const doc = dom.window.document;

let ok = false;
for (let i = 0; i < 40; i++) {
  await sleep(250);
  if (doc.querySelectorAll("#events tbody tr").length > 0 &&
      doc.querySelectorAll("#trends tbody tr").length > 0) { ok = true; break; }
}

const meta = doc.getElementById("meta").textContent;
const evRows = doc.querySelectorAll("#events tbody tr");
const trRows = doc.querySelectorAll("#trends tbody tr");
console.log("meta line:", meta);
console.log("event rows:", evRows.length, "| trend rows:", trRows.length);

const fail = (msg) => { console.error("FAIL:", msg); process.exit(1); };
if (!ok) fail("tables never rendered: " + meta);
if (meta.includes("Failed")) fail(meta);
if (!/\d{4}-\d{2}-\d{2}/.test(meta)) fail("meta missing a date");

// "Most likely to homer" section: visible, ranked by expectancy desc.
const likelySection = doc.getElementById("likely-section");
if (likelySection.hidden) fail("most-likely section is hidden");
const mlRows = [...doc.querySelectorAll("#likely tbody tr")];
if (mlRows.length === 0) fail("most-likely table has no rows");
const mlScores = mlRows.map((r) => parseFloat(r.querySelectorAll("td")[3].textContent));
for (let i = 1; i < mlScores.length; i++)
  if (mlScores[i] > mlScores[i - 1]) fail("most-likely not ranked by expectancy desc");
const hitrate = doc.getElementById("ml-hitrate").textContent;
if (!hitrate.startsWith("Track record")) fail("hit-rate line missing: " + hitrate);
const mcHits = doc.getElementById("mc-hits");
if (!mcHits) fail("model-check bucket missing from page");

// Section order: most-likely, then trending players, then the events table.
const order = [...doc.querySelectorAll("main table")].map((t) => t.id);
if (JSON.stringify(order) !== JSON.stringify(["likely", "trends", "events"]))
  fail("section order wrong: " + order.join(","));
console.log("most-likely rows:", mlRows.length, "| top score:", mlScores[0]);
console.log("model-check chips:", mcHits.querySelectorAll(".hit-chip").length,
  mcHits.hidden ? "(hidden — none yet)" : "(visible)");
console.log("hit-rate line:", hitrate);

// First event row should be the top barrel_score event (default sort desc).
const firstCells = [...evRows[0].querySelectorAll("td")].map((t) => t.textContent);
console.log("top event row:", firstCells.slice(0, 9).join(" | "));
const scores = [...evRows].map((r) => parseFloat(r.querySelectorAll("td")[8].textContent));
for (let i = 1; i < scores.length; i++)
  if (scores[i] > scores[i - 1]) fail("events not sorted by barrel score desc");

// Exercise sorting: click "HR parks" header, expect desc order by parks.
const parksTh = doc.querySelector('#events th[data-k="would_be_hr_count"]');
parksTh.dispatchEvent(new dom.window.Event("click", { bubbles: true }));
const parks = [...doc.querySelectorAll("#events tbody tr")]
  .map((r) => r.querySelectorAll("td")[7].textContent)
  .map((v) => (v === "—" ? -1 : parseInt(v)));
for (let i = 1; i < parks.length; i++)
  if (parks[i] > parks[i - 1]) fail("click-sort by HR parks did not sort desc");
console.log("click-sort by HR parks: top value =", parks[0]);

// Exercise team filter on trends.
const teamSel = doc.getElementById("tr-team");
teamSel.value = teamSel.options[1].value;
teamSel.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
const filtered = [...doc.querySelectorAll("#trends tbody tr")];
if (filtered.length === 0) fail("team filter produced zero rows");
const badTeam = filtered.find((r) => r.querySelectorAll("td")[1].textContent !== teamSel.value);
if (badTeam) fail("team filter leaked another team");
console.log(`team filter '${teamSel.value}': ${filtered.length} rows, all match`);

console.log("PAGE SMOKE TEST PASSED");
process.exit(0);
