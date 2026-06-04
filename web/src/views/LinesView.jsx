import { useEffect, useState } from 'react'
import { api, LINE_COLORS, shortLine, delayColor } from '../api'

const Dot = ({ r }) => <span className="dotc" style={{ background: LINE_COLORS[r] || '#888' }} />

export default function LinesView() {
  const [delays, setDelays] = useState([])
  const [hist, setHist] = useState({ by_route: [], by_hour_et: [] })
  const [err, setErr] = useState(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [d, h] = await Promise.all([api('/delays'), api('/history')])
        if (active) { setDelays(d.by_line || []); setHist(h); setErr(null) }
      } catch { if (active) setErr('failed to load') }
    }
    load()
    const t = setInterval(load, 30000)
    return () => { active = false; clearInterval(t) }
  }, [])

  const maxHour = Math.max(1, ...(hist.by_hour_et || []).map((x) => x.avg_delay_min))
  if (err) return <div className="wrap"><div className="empty err">{err}</div></div>

  return (
    <div className="wrap">
      <h2>Right now (current snapshot)</h2>
      {delays.length ? (
        <table><thead><tr><th>Line</th><th>Trains</th><th>Avg delay</th><th>Max</th><th>On-time</th></tr></thead>
          <tbody>{delays.map((r) => (
            <tr key={r.route_id}><td><Dot r={r.route_id} /> {shortLine(r.route_id)}</td>
              <td>{r.trains}</td>
              <td style={{ color: delayColor(r.avg_delay_min * 60) }}>{r.avg_delay_min.toFixed(1)}m</td>
              <td>{r.max_delay_min.toFixed(1)}m</td><td>{r.pct_on_time}%</td></tr>
          ))}</tbody></table>
      ) : <div className="empty">No active trains.</div>}

      <h2>Historical on-time (within 5 min, last observed delay)</h2>
      {(hist.by_route || []).length ? (
        <table><thead><tr><th>Line</th><th>Trips</th><th>Avg</th><th>Worst</th><th>On-time</th></tr></thead>
          <tbody>{hist.by_route.map((r) => (
            <tr key={r.route_id}><td><Dot r={r.route_id} /> {shortLine(r.route_id)}</td>
              <td>{r.trips}</td><td>{r.avg_delay_min}m</td><td>{r.worst_min}m</td>
              <td><span className="bar" style={{ width: Math.round(r.on_time_pct) + 'px' }} /> {r.on_time_pct}%</td></tr>
          ))}</tbody></table>
      ) : <div className="empty">Accruing…</div>}

      <h2>System delay by hour (Eastern)</h2>
      {(hist.by_hour_et || []).length ? (
        <table><tbody>{hist.by_hour_et.map((r) => (
          <tr key={r.et_hour}><td style={{ width: 60 }}>{String(r.et_hour).padStart(2, '0')}:00</td>
            <td><span className="bar" style={{ width: Math.round(220 * r.avg_delay_min / maxHour) + 'px',
              background: delayColor(r.avg_delay_min * 60) }} /> {r.avg_delay_min}m</td></tr>
        ))}</tbody></table>
      ) : <div className="empty">Accruing…</div>}
    </div>
  )
}
