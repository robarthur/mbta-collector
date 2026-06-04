import { useEffect, useState } from 'react'
import { api, LINE_COLORS, shortLine, delayColor, fmtDelay, fmtTime } from '../api'

export default function StationsView() {
  const [stops, setStops] = useState([])
  const [stop, setStop] = useState('place-north')
  const [board, setBoard] = useState([])
  const [err, setErr] = useState(null)

  useEffect(() => { api('/stops').then((d) => setStops(d.stops || [])).catch(() => {}) }, [])

  useEffect(() => {
    if (!stop) return
    let active = true
    const load = async () => {
      try {
        const d = await api('/station?stop=' + encodeURIComponent(stop))
        if (active) { setBoard(d.departures || []); setErr(null) }
      } catch { if (active) setErr('failed to load board') }
    }
    load()
    const t = setInterval(load, 30000)
    return () => { active = false; clearInterval(t) }
  }, [stop])

  return (
    <div className="wrap">
      <label className="meta">Station&nbsp;
        <select value={stop} onChange={(e) => setStop(e.target.value)}
          style={{ background: 'var(--panel)', color: 'var(--text)', border: '1px solid var(--line)',
            borderRadius: 8, padding: '6px 10px', fontSize: 14 }}>
          {stops.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>

      <h2>Next trains</h2>
      {err && <div className="empty err">{err}</div>}
      {board.length ? (
        <table>
          <thead><tr><th>Sched</th><th>Expected</th><th>Destination</th><th>Line</th><th>Delay</th><th>Status</th></tr></thead>
          <tbody>{board.map((r, i) => (
            <tr key={i}>
              <td className="meta">{fmtTime(r.scheduled_time)}</td>
              <td>{fmtTime(r.predicted_time)}</td>
              <td>{r.headsign}</td>
              <td><span className="dotc" style={{ background: LINE_COLORS[r.route_id] || '#888' }} /> {shortLine(r.route_id)}</td>
              <td style={{ color: delayColor(r.delay_s) }}>{fmtDelay(r.delay_s)}</td>
              <td>{r.status || '—'}</td>
            </tr>
          ))}</tbody>
        </table>
      ) : !err && <div className="empty">No upcoming trains.</div>}
    </div>
  )
}
