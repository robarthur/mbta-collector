import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
      const lo = parseInt(p.range.low, 10), hi = parseInt(p.range.high, 10)
      const sorted = [...p.range.tracks].sort((a, b) => parseInt(a, 10) - parseInt(b, 10))
      // If the range skips tracks, list the actual platforms so the span isn't misleading.
      const gappy = !(Number.isFinite(lo) && Number.isFinite(hi)) || sorted.length !== hi - lo + 1
      return (
        <span style={{ color: 'var(--muted)' }}>
          Plat {p.range.low}–{p.range.high}{' '}
          <span className="meta">
            ~{p.range.confidence}%{gappy ? ' · ' + sorted.join('/') : ''} · n={p.n_samples}
          </span>
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

const EFFECT_LABEL = {
  CANCELLATION: 'Cancelled', NO_SERVICE: 'No service', TRACK_CHANGE: 'Track change',
  DELAY: 'Delayed', SUSPENSION: 'Suspended', SHUTTLE: 'Shuttle', DETOUR: 'Detour',
}

// Per-row status: an alert on this train wins (Cancelled/Track change/…), else delay/feed text.
function Status({ row: r, cancelled }) {
  if (cancelled) return <span style={{ color: 'var(--red)', fontWeight: 600 }}>Cancelled</span>
  if (r.alert_effect && EFFECT_LABEL[r.alert_effect])
    return <span style={{ color: 'var(--amber)' }}>{EFFECT_LABEL[r.alert_effect]}</span>
  const color = r.predicted_time ? delayColor(r.delay_s) : 'var(--muted)'
  const text = r.delay_s != null && Math.abs(r.delay_s) > 60
    ? fmtDelay(r.delay_s)
    : r.predicted_time ? (r.status || 'On time') : 'Scheduled'
  return <span style={{ color }}>{text}</span>
}

// Station-level service alerts shown above the boards. Cancellations/suspensions red, rest amber.
function Alerts({ items }) {
  if (!items || !items.length) return null
  const red = new Set(['CANCELLATION', 'NO_SERVICE', 'SUSPENSION', 'STATION_CLOSURE', 'STOP_CLOSURE'])
  return (
    <div className="alerts">
      {items.map((a, i) => (
        <div key={i} className={'alert' + (red.has(a.effect) ? ' alert-red' : '')}>
          <b>{EFFECT_LABEL[a.effect] || a.effect}</b> {a.header}
        </div>
      ))}
    </div>
  )
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
          <tbody>{rows.map((r, i) => {
            const cancelled = r.alert_effect === 'CANCELLATION' || r.alert_effect === 'NO_SERVICE'
            return (
            <tr key={i} style={cancelled ? { opacity: 0.6 } : undefined}>
              <td style={cancelled ? { textDecoration: 'line-through' } : undefined}>
                {fmtTime(r.predicted_time || r.scheduled_time)}{' '}
                {r.predicted_time && r.scheduled_time && r.scheduled_time !== r.predicted_time &&
                  <span className="meta">(was {fmtTime(r.scheduled_time)})</span>}
              </td>
              <td>{r.headsign}{r.trip_name ? ' · ' + r.trip_name : ''}</td>
              <td><span className="dotc" style={{ background: LINE_COLORS[r.route_id] || '#888' }} /> {shortLine(r.route_id)}</td>
              <td><Platform row={r} /></td>
              <td><Status row={r} cancelled={cancelled} /></td>
            </tr>
          )})}</tbody>
        </table>
      ) : <div className="empty">No upcoming Commuter Rail trains.</div>}
    </>
  )
}

export default function StationsView() {
  const [stops, setStops] = useState([])
  const [params, setParams] = useSearchParams()
  const stop = params.get('stop') || 'place-north'
  const setStop = (s) => setParams({ stop: s }, { replace: true })  // shareable URL, no history spam
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
      <Alerts items={board.alerts} />
      <Board title={`Departures — ${stationName || '…'}`} rows={departures} loading={loading} />
      <Board title="Arrivals" rows={arrivals} loading={loading} />
    </div>
  )
}
