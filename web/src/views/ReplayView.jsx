import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import { LINE_COLORS, shortLine, delayColor, fmtDelay } from '../api'
import { useAnimatedMarkers } from '../useAnimatedMarkers'

// Replay a recorded service day from pre-baked static JSON (web/public/replay/<date>.json,
// see scripts/export-replay.py). Positions are lerped between 2-minute snapshots by the
// same imperative marker loop as the live map, driven by a scrubbable simulated clock.

const SPEEDS = [10, 60, 300]
const GRACE_MS = 150_000  // keep a train visible briefly past its last fix

const fmtClock = (ms) => new Date(ms).toLocaleTimeString('en-US',
  { timeZone: 'America/New_York', hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })

function loadDay(raw) {
  const epoch = raw.times.map((t) => Date.parse(t))
  const trains = Object.entries(raw.trains).map(([id, t]) => {
    const pts = t.pts
    return { id, name: t.name, route: t.route, dir: t.dir, pts,
             t0: epoch[pts[0][0]], t1: epoch[pts[pts.length - 1][0]] }
  })
  return { date: raw.date, epoch, trains, start: epoch[0], end: epoch[epoch.length - 1] }
}

// position + state of a train at simTime, advancing its monotonic cursor
function sample(train, epoch, simTime, cursors) {
  const pts = train.pts
  let c = cursors.get(train.id) || 0
  while (c + 1 < pts.length && epoch[pts[c + 1][0]] <= simTime) c++
  cursors.set(train.id, c)
  const a = pts[c]
  const b = pts[c + 1]
  if (!b || epoch[a[0]] > simTime) return { pos: [a[1], a[2]], delay: a[3], status: a[4] }
  const span = epoch[b[0]] - epoch[a[0]]
  const p = span > 0 ? Math.min(1, (simTime - epoch[a[0]]) / span) : 1
  return { pos: [a[1] + (b[1] - a[1]) * p, a[2] + (b[2] - a[2]) * p],
           delay: a[3], status: a[4] }
}

export default function ReplayView() {
  const [index, setIndex] = useState(null)
  const [date, setDate] = useState(null)
  const [day, setDay] = useState(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(60)
  const [simView, setSimView] = useState(0)   // low-rate mirror of simRef for React
  const [err, setErr] = useState(null)

  const simRef = useRef(0)
  const playRef = useRef(false)
  const speedRef = useRef(60)
  const lastWall = useRef(null)
  const cursors = useRef(new Map())
  const dayRef = useRef(null)
  playRef.current = playing
  speedRef.current = speed
  dayRef.current = day

  useEffect(() => {
    fetch('/replay/index.json').then((r) => r.json())
      .then((ix) => { setIndex(ix); if (ix.days?.length) setDate(ix.days[0].date) })
      .catch(() => setErr('no replay data published'))
  }, [])

  useEffect(() => {
    if (!date) return
    setDay(null)
    fetch(`/replay/${date}.json`).then((r) => r.json())
      .then((raw) => {
        const d = loadDay(raw)
        cursors.current = new Map()
        // start mid-morning (07:30 ET) where there's action, not at 03:00
        simRef.current = Math.min(d.start + 4.5 * 3600_000, d.end)
        lastWall.current = null
        setDay(d)
        setSimView(simRef.current)
      })
      .catch(() => setErr('failed to load replay day'))
  }, [date])

  // the shared rAF loop: advance the simulated clock, return per-train positions
  const registerRef = useAnimatedMarkers((now) => {
    const d = dayRef.current
    if (!d) return null
    if (playRef.current) {
      if (lastWall.current != null) {
        simRef.current = Math.min(simRef.current + (now - lastWall.current) * speedRef.current, d.end)
      }
      lastWall.current = now
    } else {
      lastWall.current = null
    }
    const sim = simRef.current
    const pos = new Map()
    for (const t of d.trains) {
      if (sim >= t.t0 && sim <= t.t1 + GRACE_MS) {
        pos.set(t.id, sample(t, d.epoch, sim, cursors.current).pos)
      }
    }
    return pos
  })

  // low-rate React tick: marker mount/unmount, colors, clock, scrubber, ticker
  useEffect(() => {
    const t = setInterval(() => {
      setSimView(simRef.current)
      if (playing && dayRef.current && simRef.current >= dayRef.current.end) setPlaying(false)
    }, 250)
    return () => clearInterval(t)
  }, [playing])

  const seek = (ms) => {
    if (ms < simRef.current) cursors.current = new Map()  // cursors are forward-only
    simRef.current = ms
    setSimView(ms)
  }

  if (err) return <div className="wrap"><div className="empty err">{err}</div></div>
  if (!index || !day) return <div className="wrap"><div className="empty">Loading replay…</div></div>

  const sim = simView
  const active = day.trains
    .filter((t) => sim >= t.t0 && sim <= t.t1 + GRACE_MS)
    .map((t) => ({ ...t, ...sample(t, day.epoch, sim, cursors.current) }))
  const worst = [...active].filter((t) => t.delay != null)
    .sort((a, b) => b.delay - a.delay).slice(0, 8)
  const byLine = {}
  for (const t of active) {
    if (t.delay != null) (byLine[t.route] = byLine[t.route] || []).push(t.delay)
  }
  const lineAvgs = Object.entries(byLine)
    .map(([r, ds]) => [r, ds.reduce((s, x) => s + x, 0) / ds.length])
    .sort((a, b) => b[1] - a[1])

  return (
    <div className="wrap">
      <div className="replay-bar">
        <select value={date} onChange={(e) => setDate(e.target.value)} className="combo-input" style={{ minWidth: 0 }}>
          {index.days.map((d) => <option key={d.date} value={d.date}>{d.date} — {d.label}</option>)}
        </select>
        <button className="chip" onClick={() => setPlaying(!playing)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
        {SPEEDS.map((s) => (
          <button key={s} className={'chip' + (speed === s ? ' active' : '')}
            onClick={() => setSpeed(s)}>{s}×</button>
        ))}
        <span className="replay-clock">{fmtClock(sim)} ET</span>
        <span className="meta">{active.length} trains</span>
      </div>
      <input type="range" className="scrubber" min={day.start} max={day.end} step={30000}
        value={sim} onChange={(e) => seek(Number(e.target.value))} />
      <div className="replay-layout">
        <MapContainer center={[42.32, -71.10]} zoom={10} className="map" preferCanvas>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="© OpenStreetMap" maxZoom={18} />
          {active.map((t) => {
            const c = delayColor(t.delay)
            return (
              <CircleMarker key={t.id} center={t.pos} ref={registerRef(t.id)}
                radius={6} pathOptions={{ color: c, fillColor: c, fillOpacity: 0.9, weight: 1 }}>
                <Popup>
                  <b>{shortLine(t.route)} {t.name}</b><br />
                  Delay: <b style={{ color: c }}>{t.delay != null ? fmtDelay(t.delay) : '—'}</b><br />
                  {t.status === 'S' ? 'Stopped at station' : t.status === 'I' ? 'Arriving' : 'In transit'}
                </Popup>
              </CircleMarker>
            )
          })}
        </MapContainer>
        <div className="replay-panel">
          <h2>Most delayed now</h2>
          {worst.length ? worst.map((t) => (
            <div key={t.id} className="ticker-row">
              <span><span className="dotc" style={{ background: LINE_COLORS[t.route] || '#888' }} /> {shortLine(t.route)} {t.name}</span>
              <b style={{ color: delayColor(t.delay) }}>{fmtDelay(t.delay)}</b>
            </div>
          )) : <div className="meta">all quiet</div>}
          <h2>By line</h2>
          {lineAvgs.map(([r, avg]) => (
            <div key={r} className="ticker-row">
              <span><span className="dotc" style={{ background: LINE_COLORS[r] || '#888' }} /> {shortLine(r)}</span>
              <span style={{ color: delayColor(avg) }}>{fmtDelay(avg)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
