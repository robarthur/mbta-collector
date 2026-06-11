import { useEffect, useState } from 'react'
import { api, LINE_COLORS, shortLine, delayColor, EFFECT_LABEL } from '../api'

const Dot = ({ r }) => <span className="dotc" style={{ background: LINE_COLORS[r] || '#888' }} />
const otpColor = (p) => (p >= 85 ? 'var(--green)' : p >= 70 ? 'var(--amber)' : 'var(--red)')
const RED_EFFECTS = new Set(['CANCELLATION', 'NO_SERVICE', 'SUSPENSION', 'STATION_CLOSURE', 'STOP_CLOSURE'])

// Daily on-time trend: one bar per service day, height/color by that day's OTP.
function Spark({ days }) {
  return (
    <div className="spark">
      {days.map((d) => (
        <b key={d.service_date}
          style={{ height: Math.max(3, Math.round(28 * (d.on_time_pct || 0) / 100)),
                   background: otpColor(d.on_time_pct || 0) }}
          title={`${d.service_date}: ${d.on_time_pct}% on-time, avg ${d.avg_delay_min}m (${d.trips} trips)`} />
      ))}
    </div>
  )
}

export default function LinesView() {
  const [delays, setDelays] = useState([])
  const [hist, setHist] = useState({ by_route: [], by_day: [], by_hour_et: [] })
  const [alerts, setAlerts] = useState([])
  const [open, setOpen] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [d, h, a] = await Promise.all([api('/delays'), api('/history'), api('/alerts')])
        if (active) { setDelays(d.by_line || []); setHist(h); setAlerts(a.alerts || []); setErr(null) }
      } catch { if (active) setErr('failed to load') }
    }
    load()
    const t = setInterval(load, 60000)
    return () => { active = false; clearInterval(t) }
  }, [])

  if (err) return <div className="wrap"><div className="empty err">{err}</div></div>

  const now = Object.fromEntries(delays.map((r) => [r.route_id, r]))
  const lineAlerts = (rid) => alerts.filter((a) => (a.routes || []).includes(rid))
  const ranked = [...(hist.by_route || [])].sort((a, b) => (b.on_time_pct || 0) - (a.on_time_pct || 0))
  const nDays = new Set((hist.by_day || []).map((d) => d.service_date)).size
  const maxHour = Math.max(1, ...(hist.by_hour_et || []).map((x) => x.avg_delay_min))

  return (
    <div className="wrap">
      <h2>Line reliability — last {nDays} days (on-time = within 5 min)</h2>
      <div className="hint">Click a line for its daily trend and active service alerts.</div>
      {ranked.length ? (
        <table>
          <thead><tr><th>Line</th><th>On-time</th><th>Avg</th><th>Worst</th><th>Right now</th><th /></tr></thead>
          <tbody>{ranked.map((r) => {
            const rid = r.route_id
            const cur = now[rid]
            const al = lineAlerts(rid)
            const isOpen = open === rid
            return [
              <tr key={rid} className="rowx" onClick={() => setOpen(isOpen ? null : rid)}>
                <td><Dot r={rid} /> {shortLine(rid)}</td>
                <td>
                  <span className="bar" style={{ width: Math.round(r.on_time_pct) + 'px',
                    background: otpColor(r.on_time_pct) }} />{' '}
                  <b style={{ color: otpColor(r.on_time_pct) }}>{r.on_time_pct}%</b>
                </td>
                <td style={{ color: delayColor(r.avg_delay_min * 60) }}>{r.avg_delay_min}m</td>
                <td className="meta">{r.worst_min}m</td>
                <td className="meta">{cur ? `${cur.trains} trains · ${cur.avg_delay_min.toFixed(1)}m` : '—'}</td>
                <td>{al.length > 0 && <span className="alert-badge">⚠ {al.length}</span>}</td>
              </tr>,
              isOpen && (
                <tr key={rid + ':detail'} className="detail">
                  <td colSpan={6}>
                    <div className="meta" style={{ margin: '4px 0' }}>Daily on-time % ({r.trips} trips total)</div>
                    <Spark days={[...(hist.by_day || [])].filter((d) => d.route_id === rid).reverse()} />
                    {al.length ? (
                      <div className="alerts" style={{ marginTop: 8 }}>
                        {[...al].sort((a) => (a.tier === 'urgent' ? -1 : 1)).map((a, i) => (
                          <div key={i} className={'alert' + (RED_EFFECTS.has(a.effect) ? ' alert-red' : '')}>
                            <b>{EFFECT_LABEL[a.effect] || a.effect}</b> {a.header}
                          </div>
                        ))}
                      </div>
                    ) : <div className="meta">No active service alerts.</div>}
                  </td>
                </tr>
              ),
            ]
          })}</tbody>
        </table>
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
