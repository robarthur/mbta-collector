import { useEffect, useState } from 'react'
import { api, LINE_COLORS, shortLine, delayColor, fmtDelay, fmtTime } from '../api'

// RTT-style platform: green + bold when confirmed by the board; grey (with confidence + n)
// when it's our prediction; em-dash when we have neither.
function Platform({ row }) {
  if (row.confirmed_track) {
    return <b style={{ color: 'var(--green)' }}>Plat {row.confirmed_track}</b>
  }
  if (row.prediction) {
    const p = row.prediction
    return (
      <span style={{ color: 'var(--muted)' }}>
        Plat {p.predicted_track}{' '}
        <span className="meta">~{p.confidence}% · n={p.n_samples}</span>
      </span>
    )
  }
  return <span className="meta">—</span>
}

function Board({ title, rows }) {
  return (
    <>
      <h2>{title}</h2>
      {rows.length ? (
        <table>
          <thead><tr><th>Time</th><th>Destination</th><th>Line</th><th>Platform</th><th>Status</th></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i}>
              <td>{fmtTime(r.predicted_time)}{' '}
                {r.scheduled_time && r.scheduled_time !== r.predicted_time &&
                  <span className="meta">(was {fmtTime(r.scheduled_time)})</span>}
              </td>
              <td>{r.headsign}{r.trip_name ? ' · ' + r.trip_name : ''}</td>
              <td><span className="dotc" style={{ background: LINE_COLORS[r.route_id] || '#888' }} /> {shortLine(r.route_id)}</td>
              <td><Platform row={r} /></td>
              <td style={{ color: delayColor(r.delay_s) }}>
                {r.delay_s != null && Math.abs(r.delay_s) > 60 ? fmtDelay(r.delay_s) : (r.status || 'On time')}
              </td>
            </tr>
          ))}</tbody>
        </table>
      ) : <div className="empty">None.</div>}
    </>
  )
}

export default function StationsView() {
  const [stops, setStops] = useState([])
  const [stop, setStop] = useState('place-north')
  const [trains, setTrains] = useState([])
  const [err, setErr] = useState(null)

  useEffect(() => { api('/stops').then((d) => setStops(d.stops || [])).catch(() => {}) }, [])

  useEffect(() => {
    if (!stop) return
    let active = true
    const load = async () => {
      try {
        const d = await api('/station?stop=' + encodeURIComponent(stop))
        if (active) { setTrains(d.trains || []); setErr(null) }
      } catch { if (active) setErr('failed to load board') }
    }
    load()
    const t = setInterval(load, 30000)
    return () => { active = false; clearInterval(t) }
  }, [stop])

  const departures = trains.filter((t) => t.direction_id === 0)
  const arrivals = trains.filter((t) => t.direction_id === 1)

  return (
    <div className="wrap">
      <label className="meta">Station&nbsp;
        <select value={stop} onChange={(e) => setStop(e.target.value)}
          style={{ background: 'var(--panel)', color: 'var(--text)', border: '1px solid var(--line)',
            borderRadius: 8, padding: '6px 10px', fontSize: 14 }}>
          {stops.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
      <div className="hint" style={{ marginTop: 10 }}>
        Platform: <b style={{ color: 'var(--green)' }}>green = confirmed</b> by the board ·
        <span style={{ color: 'var(--muted)' }}> grey = our prediction (confidence · sample size)</span>.
      </div>
      {err && <div className="empty err">{err}</div>}
      <Board title="Departures" rows={departures} />
      <Board title="Arrivals" rows={arrivals} />
    </div>
  )
}
