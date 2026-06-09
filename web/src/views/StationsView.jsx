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
    // Low modal confidence -> show the contiguous platform range that covers most history.
    if (p.range && p.range.low !== p.range.high) {
      return (
        <span style={{ color: 'var(--muted)' }} title={'Likely tracks: ' + p.range.tracks.join(', ')}>
          Plat {p.range.low}–{p.range.high}{' '}
          <span className="meta">~{p.range.confidence}% · n={p.n_samples}</span>
        </span>
      )
    }
    return (
      <span style={{ color: 'var(--muted)' }}>
        Plat {p.predicted_track}{' '}
        <span className="meta">~{p.confidence}% · n={p.n_samples}</span>
      </span>
    )
  }
  return <span className="meta">—</span>
}

function Board({ title, rows, loading }) {
  return (
    <>
      <h2>{title}</h2>
      {loading ? (
        <div className="empty">Loading…</div>
      ) : rows.length ? (
        <table>
          <thead><tr><th>Time</th><th>Destination</th><th>Line</th><th>Platform</th><th>Status</th></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i}>
              <td>{fmtTime(r.predicted_time || r.scheduled_time)}{' '}
                {r.predicted_time && r.scheduled_time && r.scheduled_time !== r.predicted_time &&
                  <span className="meta">(was {fmtTime(r.scheduled_time)})</span>}
              </td>
              <td>{r.headsign}{r.trip_name ? ' · ' + r.trip_name : ''}</td>
              <td><span className="dotc" style={{ background: LINE_COLORS[r.route_id] || '#888' }} /> {shortLine(r.route_id)}</td>
              <td><Platform row={r} /></td>
              <td style={{ color: r.predicted_time ? delayColor(r.delay_s) : 'var(--muted)' }}>
                {r.delay_s != null && Math.abs(r.delay_s) > 60
                  ? fmtDelay(r.delay_s)
                  : r.predicted_time ? (r.status || 'On time') : 'Scheduled'}
              </td>
            </tr>
          ))}</tbody>
        </table>
      ) : <div className="empty">No upcoming Commuter Rail trains.</div>}
    </>
  )
}

export default function StationsView() {
  const [stops, setStops] = useState([])
  const [stop, setStop] = useState('place-north')
  const [board, setBoard] = useState({})
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => { api('/stops').then((d) => setStops(d.stops || [])).catch(() => {}) }, [])

  useEffect(() => {
    if (!stop) return
    let active = true
    setBoard({}); setLoading(true)  // clear immediately so the station change is visible
    const load = async (showLoading) => {
      if (showLoading) setLoading(true)
      try {
        const d = await api('/station?stop=' + encodeURIComponent(stop))
        if (active) { setBoard(d); setErr(null) }
      } catch { if (active) setErr('failed to load board') }
      finally { if (active) setLoading(false) }
    }
    load(true)
    const t = setInterval(() => load(false), 30000)  // background refresh, no loading flash
    return () => { active = false; clearInterval(t) }
  }, [stop])

  const stationName = stops.find((s) => s.id === stop)?.name

  const departures = board.departures || []
  const arrivals = board.arrivals || []

  return (
    <div className="wrap">
      <label className="meta">Station&nbsp;
        <select value={stop} onChange={(e) => setStop(e.target.value)}
          style={{ background: 'var(--panel)', color: 'var(--text)', border: '1px solid var(--line)',
            borderRadius: 8, padding: '6px 10px', fontSize: 14, minWidth: 220 }}>
          {stops.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>
      <div className="hint" style={{ marginTop: 10 }}>
        Platform: <b style={{ color: 'var(--green)' }}>green = confirmed</b> by the board ·
        <span style={{ color: 'var(--muted)' }}> grey = our prediction (confidence · sample size)</span>.
      </div>
      {err && <div className="empty err">{err}</div>}
      <Board title={`Departures — ${stationName || '…'}`} rows={departures} loading={loading} />
      <Board title="Arrivals" rows={arrivals} loading={loading} />
    </div>
  )
}
