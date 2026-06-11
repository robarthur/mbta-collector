import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import { api, LINE_COLORS, shortLine, delayColor, fmtDelay } from '../api'

function Chip({ label, color, active, onClick }) {
  return (
    <button className={'chip' + (active ? ' active' : '')} onClick={onClick}>
      {color && <span className="dotc" style={{ background: color }} />}
      {label}
    </button>
  )
}

export default function MapView() {
  const [trains, setTrains] = useState([])
  const [line, setLine] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const d = await api('/live-trains')   // seconds-fresh positions; delay joined server-side
        if (active) { setTrains(d.trains || []); setErr(null) }
      } catch { if (active) setErr('failed to load trains') }
    }
    load()
    const t = setInterval(load, 15000)
    return () => { active = false; clearInterval(t) }
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
        {shown.map((t, i) => {
          const c = delayColor(t.delay_s)
          return (
            <CircleMarker key={i} center={[t.latitude, t.longitude]} radius={6}
              pathOptions={{ color: c, fillColor: c, fillOpacity: 0.9, weight: 1 }}>
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
