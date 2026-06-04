"""Self-contained MBTA Commuter Rail webapp (vanilla HTML/CSS/JS, no build step).

Three views — Map (live positions+delays), Lines (delay + historical OTP), Platforms
(track board + predictions) — all consuming the existing JSON endpoints. Leaflet via CDN.
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MBTA Commuter Rail — live, delays, platforms</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root { --cr:#80276C; --bg:#0f1115; --panel:#181b22; --line:#272b35;
          --text:#e7e9ee; --muted:#9aa1ad; --green:#1f8f4e; --amber:#d99a1e;
          --red:#e2706b; --blue:#3b82f6; --grey:#5a6072; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  header { padding:14px 20px; border-bottom:1px solid var(--line); display:flex;
           align-items:center; gap:16px; flex-wrap:wrap; }
  h1 { font-size:16px; margin:0; font-weight:650; } h1 .dot { color:var(--cr); }
  .meta { color:var(--muted); font-size:12px; }
  .views { display:flex; gap:8px; margin-left:auto; }
  .vtab { padding:7px 14px; border:1px solid var(--line); background:var(--panel);
          color:var(--text); border-radius:999px; cursor:pointer; font-size:14px; }
  .vtab.active { background:var(--cr); border-color:var(--cr); color:#fff; }
  .wrap { padding:16px 20px; max-width:1100px; margin:0 auto; }
  #map { height:calc(100vh - 150px); border-radius:10px; border:1px solid var(--line); }
  .chips { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
  .chip { padding:4px 10px; border-radius:999px; border:1px solid var(--line);
          background:var(--panel); color:var(--text); cursor:pointer; font-size:12.5px;
          display:flex; gap:6px; align-items:center; white-space:nowrap; }
  .chip.active { outline:2px solid var(--cr); }
  .dotc { width:9px; height:9px; border-radius:50%; display:inline-block; }
  .legend { color:var(--muted); font-size:12px; margin:8px 0 0; display:flex; gap:14px; flex-wrap:wrap; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); font-size:14px; }
  th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.5px; }
  h2 { font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.6px; margin:20px 0 8px; }
  .bar { height:8px; border-radius:4px; background:var(--cr); display:inline-block; vertical-align:middle; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:600; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(110px,1fr)); gap:9px; }
  .cell { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:11px; min-height:70px; }
  .cell.occ { border-color:var(--cr); box-shadow:inset 0 0 0 1px var(--cr); }
  .cell .num { font-size:24px; font-weight:700; } .cell .who,.cell .trk { font-size:12px; color:var(--muted); }
  .hint { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px;
          color:var(--muted); font-size:13px; margin-bottom:12px; }
  .empty { color:var(--muted); padding:12px 0; } .err { color:var(--red); }
  .htab { padding:6px 12px; border:1px solid var(--line); background:var(--panel); color:var(--text);
          border-radius:999px; cursor:pointer; font-size:13px; }
  .htab.active { background:var(--cr); border-color:var(--cr); color:#fff; }
  footer { color:var(--muted); font-size:12px; padding:14px 20px; border-top:1px solid var(--line); }
  footer a { color:var(--muted); }
</style>
</head>
<body>
<header>
  <h1><span class="dot">●</span> MBTA Commuter Rail</h1>
  <span class="meta" id="meta">loading…</span>
  <div class="views">
    <button class="vtab active" data-view="map">Map</button>
    <button class="vtab" data-view="lines">Lines</button>
    <button class="vtab" data-view="platforms">Platforms</button>
  </div>
</header>

<div class="wrap">
  <div id="view-map">
    <div class="chips" id="lineChips"></div>
    <div id="map"></div>
    <div class="legend">
      <span><span class="dotc" style="background:var(--blue)"></span> early</span>
      <span><span class="dotc" style="background:var(--green)"></span> ≤2 min</span>
      <span><span class="dotc" style="background:var(--amber)"></span> 2–5 min</span>
      <span><span class="dotc" style="background:var(--red)"></span> &gt;5 min late</span>
      <span id="mapcount"></span>
    </div>
  </div>

  <div id="view-lines" style="display:none">
    <h2>Right now (current snapshot)</h2>
    <div id="linesNow"></div>
    <h2>Historical on-time performance (within 5 min, last observed delay)</h2>
    <div id="linesHist"></div>
    <h2>System delay by hour (Eastern)</h2>
    <div id="byHour"></div>
  </div>

  <div id="view-platforms" style="display:none">
    <div class="chips" id="stationChips"></div>
    <div class="hint" id="zoneHint"></div>
    <h2>Platform occupancy</h2>
    <div class="grid" id="pgrid"></div>
    <h2>Inbound trains</h2>
    <div id="pinbound"></div>
    <h2>Recent platform resolutions (all stations)</h2>
    <div id="pevents"></div>
  </div>
</div>

<footer>
  Data via the MBTA V3 API, refreshed ~30s. JSON:
  <a href="/trains">/trains</a> · <a href="/delays">/delays</a> ·
  <a href="/history">/history</a> · <a href="/board?station=north">/board</a> ·
  <a href="/turn-lead">/turn-lead</a> · <a href="/health">/health</a>
</footer>

<script>
const LINE_COLORS = {
  "CR-Fitchburg":"#e6794b","CR-Lowell":"#5fb0e6","CR-Haverhill":"#b06be0",
  "CR-Newburyport":"#e6c84b","CR-Worcester":"#5fd896","CR-Franklin":"#e65f8a",
  "CR-Needham":"#9ad14b","CR-Providence":"#e64b4b","CR-Fairmount":"#4be6d0",
  "CR-Greenbush":"#8a9ae6","CR-Kingston":"#d68a5f","CR-NewBedford":"#c0e64b",
  "CR-Foxboro":"#e6b0d0"
};
const ZONE_HINT = {
  north:"Predicted zone: Eastern Route (Newburyport/Rockport, Haverhill) → east tracks 1–5; Fitchburg & Lowell → west 6–10 (Fitchburg usually 9/10). Exact track is set late by dispatch — only the zone is reliably predictable here.",
  south:"Predicted band: Worcester→1–2, Needham→3–4, Providence→5–8, Fairmount→10, Old Colony (Greenbush/Kingston) + NewBedford→11–13. ~87% land within ±1 track of their usual.",
  backbay:"Through-station: platforms come from the schedule, so the track is usually known well in advance."
};
let currentView="map", currentLine=null, currentStation="north", map=null, markers=null;

function shortLine(r){ return (r||"").replace("CR-",""); }
function delayColor(s){ if(s==null) return "var(--grey)"; if(s<0) return "var(--blue)";
  if(s<=120) return "var(--green)"; if(s<=300) return "var(--amber)"; return "var(--red)"; }
function fmtDelay(s){ if(s==null) return "—"; const m=(s/60); return (m>=0?"+":"")+m.toFixed(1)+"m"; }
function fmtTime(iso){ if(!iso) return "—"; try { return new Date(iso).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}); } catch(e){ return iso; } }

// ---- view switching ----
document.querySelectorAll(".vtab").forEach(b => b.onclick = () => {
  currentView=b.dataset.view;
  document.querySelectorAll(".vtab").forEach(x=>x.classList.toggle("active",x===b));
  for(const v of ["map","lines","platforms"])
    document.getElementById("view-"+v).style.display = (v===currentView)?"":"none";
  if(currentView==="map" && map) setTimeout(()=>map.invalidateSize(),50);
  refresh();
});

// ---- MAP ----
function initMap(){
  map = L.map("map",{zoomControl:true}).setView([42.32,-71.10],10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {maxZoom:18, attribution:"© OpenStreetMap"}).addTo(map);
  markers = L.layerGroup().addTo(map);
  const chips=document.getElementById("lineChips");
  const mk=(label,line)=>{ const c=document.createElement("button"); c.className="chip"+((currentLine===line)?" active":"");
    c.innerHTML=(line?`<span class="dotc" style="background:${LINE_COLORS[line]}"></span>`:"")+label;
    c.onclick=()=>{ currentLine=line; document.querySelectorAll("#lineChips .chip").forEach(x=>x.classList.remove("active")); c.classList.add("active"); loadTrains(); };
    chips.appendChild(c); };
  mk("All",null);
  Object.keys(LINE_COLORS).forEach(l=>mk(shortLine(l),l));
}
async function loadTrains(){
  try {
    const url = currentLine ? "/trains?route="+encodeURIComponent(currentLine) : "/trains";
    const d = await (await fetch(url)).json();
    markers.clearLayers(); let n=0;
    for(const t of d.trains||[]){
      if(t.latitude==null||t.longitude==null) continue; n++;
      const col=delayColor(t.delay_s);
      L.circleMarker([t.latitude,t.longitude],{radius:6,color:col,fillColor:col,fillOpacity:.9,weight:1})
        .bindPopup(`<b>${shortLine(t.route_id)} ${t.trip_name||""}</b><br>`+
          `Est delay: <b style="color:${col}">${fmtDelay(t.delay_s)}</b><br>`+
          `Reported: ${t.reported_status||"—"}<br>${t.current_status||""}<br>→ ${t.next_stop_id||"?"}`)
        .addTo(markers);
    }
    document.getElementById("mapcount").textContent = n+" trains shown";
  } catch(e){ document.getElementById("mapcount").textContent="failed to load trains"; }
}

// ---- LINES ----
async function loadLines(){
  try {
    const [del,hist] = await Promise.all([
      (await fetch("/delays")).json(), (await fetch("/history")).json() ]);
    const now=del.by_line||[];
    let h="<table><thead><tr><th>Line</th><th>Trains</th><th>Avg delay</th><th>Max</th><th>On-time</th></tr></thead><tbody>";
    for(const r of now) h+=`<tr><td><span class="dotc" style="background:${LINE_COLORS[r.route_id]||'#888'}"></span> ${shortLine(r.route_id)}</td>`+
      `<td>${r.trains}</td><td style="color:${delayColor(r.avg_delay_min*60)}">${r.avg_delay_min.toFixed(1)}m</td>`+
      `<td>${r.max_delay_min.toFixed(1)}m</td><td>${r.pct_on_time}%</td></tr>`;
    document.getElementById("linesNow").innerHTML = now.length? h+"</tbody></table>" : '<div class="empty">No active trains.</div>';

    const byr=hist.by_route||[];
    let hh="<table><thead><tr><th>Line</th><th>Trips</th><th>Avg</th><th>Worst</th><th>On-time</th></tr></thead><tbody>";
    for(const r of byr) hh+=`<tr><td><span class="dotc" style="background:${LINE_COLORS[r.route_id]||'#888'}"></span> ${shortLine(r.route_id)}</td>`+
      `<td>${r.trips}</td><td>${r.avg_delay_min}m</td><td>${r.worst_min}m</td>`+
      `<td><span class="bar" style="width:${Math.round(r.on_time_pct)}px"></span> ${r.on_time_pct}%</td></tr>`;
    document.getElementById("linesHist").innerHTML = byr.length? hh+"</tbody></table>" : '<div class="empty">Accruing…</div>';

    const bh=hist.by_hour_et||[]; const mx=Math.max(1,...bh.map(x=>x.avg_delay_min));
    let bhh='<table><tbody>';
    for(const r of bh) bhh+=`<tr><td style="width:60px">${String(r.et_hour).padStart(2,'0')}:00</td>`+
      `<td><span class="bar" style="width:${Math.round(220*r.avg_delay_min/mx)}px;background:${delayColor(r.avg_delay_min*60)}"></span> ${r.avg_delay_min}m</td></tr>`;
    document.getElementById("byHour").innerHTML = bh.length? bhh+"</tbody></table>" : '<div class="empty">Accruing…</div>';
  } catch(e){ document.getElementById("linesNow").innerHTML='<div class="empty err">Failed to load.</div>'; }
}

// ---- PLATFORMS ----
function initStations(){
  const c=document.getElementById("stationChips");
  [["north","North Station"],["south","South Station"],["backbay","Back Bay"]].forEach(([k,name])=>{
    const b=document.createElement("button"); b.className="chip"+((k===currentStation)?" active":""); b.textContent=name;
    b.onclick=()=>{ currentStation=k; document.querySelectorAll("#stationChips .chip").forEach(x=>x.classList.remove("active")); b.classList.add("active"); loadBoard(); };
    c.appendChild(b);
  });
}
async function loadBoard(){
  document.getElementById("zoneHint").textContent = ZONE_HINT[currentStation]||"";
  try {
    const d = await (await fetch("/board?station="+currentStation)).json();
    const grid=document.getElementById("pgrid"); grid.innerHTML="";
    const occ=d.occupancy||{};
    for(const t of Object.keys(occ)){ const who=occ[t]; const cell=document.createElement("div");
      cell.className="cell"+(who?" occ":""); cell.innerHTML=`<div class="trk">Track</div><div class="num">${t}</div>`+
        (who?`<div class="who">${shortLine(who.route)}<br>veh ${who.vehicle||""}</div>`:`<div class="who">free</div>`);
      grid.appendChild(cell); }
    if(!Object.keys(occ).length) grid.innerHTML='<div class="empty">No track data.</div>';
    const inb=d.inbound||[];
    let h="<table><thead><tr><th>Arrival</th><th>Route</th><th>Status</th><th>Track</th></tr></thead><tbody>";
    for(const r of inb){ const pill=r.track_known?`<span class="pill" style="background:rgba(31,143,78,.2);color:#5fd896">Track ${r.track}</span>`:`<span class="pill" style="background:rgba(90,96,114,.25);color:#aab1bf">unknown</span>`;
      h+=`<tr><td>${fmtTime(r.arrival_time)}</td><td>${shortLine(r.route)}</td><td>${r.status||"—"}</td><td>${pill}</td></tr>`; }
    document.getElementById("pinbound").innerHTML = inb.length? h+"</tbody></table>" : '<div class="empty">No inbound trains.</div>';
  } catch(e){ document.getElementById("pgrid").innerHTML='<div class="empty err">Failed to load board.</div>'; }
  try {
    const rows = await (await fetch("/events")).json();
    let h="<table><thead><tr><th>Resolved</th><th>Station</th><th>Route</th><th>Track</th><th>How</th></tr></thead><tbody>";
    for(const r of rows.slice(0,15)){ const how=r.resolved_via==="vehicle_stopped_at"?"berthed":"board";
      h+=`<tr><td>${fmtTime(r.resolved_ts)}</td><td>${r.station}</td><td>${shortLine(r.route_id)}</td><td>${r.resolved_track}</td><td>${how}</td></tr>`; }
    document.getElementById("pevents").innerHTML = rows.length? h+"</tbody></table>" : '<div class="empty">No resolutions yet.</div>';
  } catch(e){}
}

async function loadHealth(){
  try { const h=await (await fetch("/health")).json();
    document.getElementById("meta").textContent =
      `${h.track_events} platform events · ${h.snapshots} snapshots · last ${fmtTime(h.last_poll_ts)}`;
  } catch(e){}
}

function refresh(){
  loadHealth();
  if(currentView==="map") loadTrains();
  else if(currentView==="lines") loadLines();
  else loadBoard();
}

initMap(); initStations(); refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""
