"""Self-contained live web board. Vanilla HTML/CSS/JS (no build step, no deps).

Consumes the existing JSON endpoints (/board?station=KEY and /health) client-side, so the
JSON API stays the single source of truth.
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>estimated-platform — MBTA CR track board</title>
<style>
  :root { --cr:#80276C; --bg:#0f1115; --panel:#181b22; --line:#272b35;
          --known:#1f8f4e; --unknown:#5a6072; --text:#e7e9ee; --muted:#9aa1ad; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  header { padding:16px 20px; border-bottom:1px solid var(--line);
           display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
  h1 { font-size:16px; margin:0; font-weight:650; letter-spacing:.2px; }
  h1 .dot { color:var(--cr); }
  .meta { color:var(--muted); font-size:12.5px; }
  .wrap { max-width:980px; margin:0 auto; padding:20px; }
  .tabs { display:flex; gap:8px; margin-bottom:18px; flex-wrap:wrap; }
  .tab { padding:8px 14px; border:1px solid var(--line); background:var(--panel);
         color:var(--text); border-radius:999px; cursor:pointer; font-size:14px; }
  .tab.active { background:var(--cr); border-color:var(--cr); color:#fff; }
  h2 { font-size:14px; color:var(--muted); text-transform:uppercase; letter-spacing:.6px;
       margin:22px 0 10px; font-weight:600; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(120px,1fr)); gap:10px; }
  .cell { background:var(--panel); border:1px solid var(--line); border-radius:10px;
          padding:12px; min-height:74px; }
  .cell .trk { font-size:12px; color:var(--muted); }
  .cell .num { font-size:26px; font-weight:700; line-height:1; margin-top:2px; }
  .cell.occ { border-color:var(--cr); box-shadow:inset 0 0 0 1px var(--cr); }
  .cell.occ .num { color:#fff; }
  .cell .who { font-size:12px; color:var(--muted); margin-top:6px; }
  .cell.free .num { color:var(--unknown); }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); font-size:14px; }
  th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.5px; }
  .pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12.5px; font-weight:600; }
  .pill.known { background:rgba(31,143,78,.18); color:#5fd896; }
  .pill.unknown { background:rgba(90,96,114,.22); color:#aab1bf; }
  .route { font-weight:600; }
  .empty { color:var(--muted); padding:14px 0; }
  footer { color:var(--muted); font-size:12px; padding:18px 20px; border-top:1px solid var(--line); }
  footer a { color:var(--muted); }
  .err { color:#e2706b; }
</style>
</head>
<body>
<header>
  <h1><span class="dot">●</span> estimated-platform</h1>
  <span class="meta" id="meta">loading…</span>
</header>
<div class="wrap">
  <div class="tabs" id="tabs"></div>
  <div id="title"></div>
  <h2>Platform occupancy</h2>
  <div class="grid" id="grid"></div>
  <h2>Inbound trains</h2>
  <div id="inbound"></div>
</div>
<footer>
  Track resolved from MBTA feeds. Green = track known, grey = not yet assigned (the
  North/South prediction gap). Raw JSON:
  <a href="/board?station=north">/board</a> ·
  <a href="/analyze">/analyze</a> ·
  <a href="/health">/health</a>. Auto-refreshes every 15s.
</footer>
<script>
const STATIONS = [["north","North Station"],["south","South Station"],["backbay","Back Bay"]];
let current = "north";

function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}); }
  catch (e) { return iso; }
}

function renderTabs() {
  const el = document.getElementById("tabs");
  el.innerHTML = "";
  for (const [key, name] of STATIONS) {
    const b = document.createElement("button");
    b.className = "tab" + (key === current ? " active" : "");
    b.textContent = name;
    b.onclick = () => { current = key; renderTabs(); load(); };
    el.appendChild(b);
  }
}

async function loadHealth() {
  try {
    const h = await (await fetch("/health")).json();
    const by = (h.events_by_station || []).map(s => `${s.station}:${s.n}`).join("  ");
    document.getElementById("meta").textContent =
      `polls ${h.polls} · observations ${h.observations} · track events ${h.track_events}` +
      (by ? `  (${by})` : "") + ` · last poll ${fmtTime(h.last_poll_ts)}`;
  } catch (e) { document.getElementById("meta").textContent = ""; }
}

function renderGrid(occ) {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  const keys = Object.keys(occ);
  if (!keys.length) { grid.innerHTML = '<div class="empty">No track data.</div>'; return; }
  for (const t of keys) {
    const who = occ[t];
    const cell = document.createElement("div");
    cell.className = "cell " + (who ? "occ" : "free");
    cell.innerHTML = `<div class="trk">Track</div><div class="num">${t}</div>` +
      (who ? `<div class="who">${who.route || ""}<br>veh ${who.vehicle || ""}</div>`
           : `<div class="who">free</div>`);
    grid.appendChild(cell);
  }
}

function renderInbound(rows) {
  const box = document.getElementById("inbound");
  if (!rows || !rows.length) { box.innerHTML = '<div class="empty">No inbound trains.</div>'; return; }
  let html = "<table><thead><tr><th>Arrival</th><th>Route</th><th>Status</th><th>Track</th></tr></thead><tbody>";
  for (const r of rows) {
    const pill = r.track_known
      ? `<span class="pill known">Track ${r.track}</span>`
      : `<span class="pill unknown">unknown</span>`;
    html += `<tr><td>${fmtTime(r.arrival_time)}</td>` +
            `<td class="route">${r.route || ""}</td>` +
            `<td>${r.status || "—"}</td><td>${pill}</td></tr>`;
  }
  box.innerHTML = html + "</tbody></table>";
}

async function load() {
  try {
    const d = await (await fetch("/board?station=" + current)).json();
    document.getElementById("title").innerHTML =
      `<div class="meta">${d.name || current} · poll ${d.poll ? fmtTime(d.poll.ts) : "—"}</div>`;
    renderGrid(d.occupancy || {});
    renderInbound(d.inbound || []);
  } catch (e) {
    document.getElementById("grid").innerHTML = '<div class="empty err">Failed to load board.</div>';
  }
  loadHealth();
}

renderTabs();
load();
setInterval(load, 15000);
</script>
</body>
</html>
"""
