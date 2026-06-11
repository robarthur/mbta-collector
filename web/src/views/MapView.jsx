import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import { api, LINE_COLORS, shortLine, delayColor, fmtDelay } from '../api'

const POLL_MS = 10000   // fetch fresh positions every 10s
const SNAP_M = 5000     // teleport (don't glide) beyond this — data corrections, tunnel GPS

function Chip({ label, color, active, onClick }) {
  return (
    <button className={'chip' + (active ? ' active' : '')} onClick={onClick}>
      {color && <span className="dotc" style={{ background: color }} />}
      {label}
    </button>
  )
}

// rough meters between [lat,lng] pairs (fine at city scale)
function distM(a, b) {
  const dx = (a[1] - b[1]) * 111320 * Math.cos((a[0] * Math.PI) / 180)
  const dy = (a[0] - b[0]) * 110540
  return Math.hypot(dx, dy)
}

// linear position along a tween at time `now` (constant speed reads as train-like)
function curPos(tw, now) {
  const p = Math.min(1, (now - tw.start) / POLL_MS)
  return [tw.from[0] + (tw.to[0] - tw.from[0]) * p,
          tw.from[1] + (tw.to[1] - tw.from[1]) * p]
}

export default function MapView() {
  const [trains, setTrains] = useState([])
  const [line, setLine] = useState(null)
  const [err, setErr] = useState(null)
  const tweens = useRef(new Map())   // vehicle_id -> {from, to, start}
  const markers = useRef(new Map())  // vehicle_id -> leaflet layer (for imperative setLatLng)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const d = await api('/live-trains')
        if (!active) return
        const now = performance.now()
        const seen = new Set()
        for (const t of d.trains || []) {
          if (t.latitude == null || t.longitude == null) continue
          seen.add(t.vehicle_id)
          const to = [t.latitude, t.longitude]
          const prev = tweens.current.get(t.vehicle_id)
          // glide from wherever the marker currently is; snap on first sight or big jumps
          let from = to
          if (prev) {
            const cur = curPos(prev, now)
            if (distM(cur, to) < SNAP_M) from = cur
          }
          tweens.current.set(t.vehicle_id, { from, to, start: now })
        }
        for (const id of tweens.current.keys()) if (!seen.has(id)) tweens.current.delete(id)
        setTrains(d.trains || []); setErr(null)
      } catch { if (active) setErr('failed to load trains') }
    }
    load()
    const t = setInterval(load, POLL_MS)
    return () => { active = false; clearInterval(t) }
  }, [])

  // One rAF loop slides every marker imperatively — no React re-render per frame.
  useEffect(() => {
    let raf
    const step = () => {
      const now = performance.now()
      for (const [id, tw] of tweens.current) {
        const m = markers.current.get(id)
        if (m) m.setLatLng(curPos(tw, now))
      }
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [])

  const shown = trains.filter((t) =>
    t.latitude != null && t.longitude != null && (!line || t.route_id === line))

  return (
    <div className="wrap">
      <div className="chips">
        <Chip label="All" active={line === null} onClick={() => setLine(null)} />
        {Object.keys(LINE_COLORS).map((l) => (
          <Chip key={l} label={shortLine(l)} color={LINE_COLORS[l]}
            active={line === l} onClick={() => setLine(l)} />
        ))}
      </div>
      <MapContainer center={[42.32, -71.10]} zoom={10} className="map" preferCanvas>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="© OpenStreetMap" maxZoom={18} />
        {shown.map((t) => {
          const c = delayColor(t.delay_s)
          const tw = tweens.current.get(t.vehicle_id)
          return (
            <CircleMarker key={t.vehicle_id}
              center={tw ? curPos(tw, performance.now()) : [t.latitude, t.longitude]}
              ref={(m) => {
                if (m) markers.current.set(t.vehicle_id, m)
                else markers.current.delete(t.vehicle_id)
              }}
              radius={6} pathOptions={{ color: c, fillColor: c, fillOpacity: 0.9, weight: 1 }}>
              <Popup>
                <b>{shortLine(t.route_id)} {t.trip_name}</b><br />
                Est delay: <b style={{ color: c }}>{t.delay_s != null ? fmtDelay(t.delay_s) : '—'}</b><br />
                Reported: {t.reported_status || '—'}<br />
                {t.current_status}<br />→ {t.next_stop_id || '?'}
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>
      <div className="legend">
        <span><span className="dotc" style={{ background: 'var(--blue)' }} /> early</span>
        <span><span className="dotc" style={{ background: 'var(--green)' }} /> ≤2 min</span>
        <span><span className="dotc" style={{ background: 'var(--amber)' }} /> 2–5 min</span>
        <span><span className="dotc" style={{ background: 'var(--red)' }} /> &gt;5 min late</span>
        <span>{err ? err : `${shown.length} trains shown`}</span>
      </div>
    </div>
  )
}
