import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, LINE_COLORS, shortLine, delayColor, fmtDelay, fmtTime, EFFECT_LABEL } from '../api'
import StationPicker from '../StationPicker.jsx'
import { supported as notifySupported, isWatched, addWatch, removeWatch, requestPermission, checkBoard } from '../watches'

// RTT-style platform: green + bold when confirmed by the board; grey (with confidence + n)
// when it's our prediction; em-dash when we have neither.
function Platform({ row }) {
  if (row.confirmed_track) {
    return <b style={{ color: 'var(--green)' }}>Plat {row.confirmed_track}</b>
  }
  // Timetabled platform (outlying multi-track stations carry it in the schedule) —
  // authoritative, so it outranks our statistical prediction.
  if (row.scheduled_track) {
    return (
      <span style={{ color: 'var(--muted)' }}>
        Plat {row.scheduled_track} <span className="meta">sched</span>
      </span>
    )
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

// Station-level service alerts. Urgent (delay/cancellation/track change) shown inline;
// informational notices (schedule changes etc.) tucked behind a dropdown to cut clutter.
const RED_EFFECTS = new Set(['CANCELLATION', 'NO_SERVICE', 'SUSPENSION', 'STATION_CLOSURE', 'STOP_CLOSURE'])
const AlertRow = ({ a }) => (
  <div className={'alert' + (RED_EFFECTS.has(a.effect) ? ' alert-red' : '')}>
    <b>{EFFECT_LABEL[a.effect] || a.effect}</b> {a.header}
  </div>
)

function Alerts({ items }) {
  if (!items || !items.length) return null
  const urgent = items.filter((a) => a.tier !== 'info')
  const info = items.filter((a) => a.tier === 'info')
  return (
    <div className="alerts">
      {urgent.map((a, i) => <AlertRow key={i} a={a} />)}
      {info.length > 0 && (
        <details className="alert-more">
          <summary>{info.length} service notice{info.length > 1 ? 's' : ''}</summary>
          {info.map((a, i) => <AlertRow key={i} a={a} />)}
        </details>
      )}
    </div>
  )
}

function Board({ title, rows, loading, watchable, onToggle }) {
  return (
    <>
      <h2>{title}</h2>
      {loading ? (
        <div className="empty">Loading…</div>
      ) : rows.length ? (
        <table>
          <thead><tr>{watchable && <th />}<th>Time</th><th>Destination</th><th>Line</th><th>Platform</th><th>Status</th></tr></thead>
          <tbody>{rows.map((r, i) => {
            const cancelled = r.alert_effect === 'CANCELLATION' || r.alert_effect === 'NO_SERVICE'
            return (
            <tr key={i} style={cancelled ? { opacity: 0.6 } : undefined}>
              {watchable && (
                <td>{r.trip_id &&
                  <button className={'bell' + (isWatched(r.trip_id) ? ' on' : '')}
                    title={isWatched(r.trip_id) ? 'Stop watching' : 'Notify me when the platform posts'}
                    onClick={() => onToggle(r)}>🔔</button>}
                </td>
              )}
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
        if (active) { setBoard(d); setErr(null); checkBoard(stop, d.departures) }
      } catch { if (active) setErr('failed to load board') }
      finally { if (active) setLoading(false) }
    }
    load(true)
    const t = setInterval(() => load(false), 30000)  // background refresh, no loading flash
    return () => { active = false; clearInterval(t) }
  }, [stop])

  const stationName = stops.find((s) => s.id === stop)?.name

  const [, setWatchTick] = useState(0)        // re-render after watch toggles (store is external)
  const [notifyMsg, setNotifyMsg] = useState(null)
  const toggleWatch = async (r) => {
    if (isWatched(r.trip_id)) {
      removeWatch(r.trip_id)
    } else {
      const perm = await requestPermission()
      if (perm !== 'granted') {
        setNotifyMsg('Notifications are blocked — allow them in your browser settings to watch trains.')
        return
      }
      addWatch(r, stop)
      setNotifyMsg(null)
    }
    setWatchTick((x) => x + 1)
  }

  const departures = board.departures || []
  const arrivals = board.arrivals || []

  return (
    <div className="wrap">
      <label className="meta">Station&nbsp;
        <StationPicker stops={stops} value={stop} onChange={setStop} />
      </label>
      <div className="hint" style={{ marginTop: 10 }}>
        Platform: <b style={{ color: 'var(--green)' }}>green = confirmed</b> by the board ·
        <span style={{ color: 'var(--muted)' }}> grey = timetabled (sched) or our prediction (confidence · sample size)</span>.
      </div>
      {err && <div className="empty err">{err}</div>}
      {notifyMsg && <div className="hint" style={{ marginTop: 10 }}>{notifyMsg}</div>}
      <Alerts items={board.alerts} />
      <Board title={`Departures — ${stationName || '…'}`} rows={departures} loading={loading}
        watchable={notifySupported} onToggle={toggleWatch} />
      {(loading || arrivals.length > 0) &&
        <Board title="Arrivals" rows={arrivals} loading={loading} />}
    </div>
  )
}
