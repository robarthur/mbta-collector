import { useEffect, useState } from 'react'
import { api, LINE_COLORS, shortLine, fmtTime } from '../api'

// Demo walkthrough (unlisted route /demo/disruption): a SIMULATED Haverhill suspension at
// Malden Center, with the impact and alternatives panels driven by LIVE data. Each "Next"
// click reveals the next beat of the story — paced for presenting, not self-serve.

const STOP = 'place-mlmnl'
const AFFECTED_ROUTE = 'CR-Haverhill'
const STEPS = ['The alert', 'The impact', 'The alternatives', 'Keep them informed']
const MODE_LABEL = { subway: 'Subway — same station', bus: 'Bus connections', cr: 'Other Commuter Rail' }

export default function DisruptionView() {
  const [step, setStep] = useState(0)
  const [board, setBoard] = useState(null)
  const [alts, setAlts] = useState(null)

  useEffect(() => {
    api('/station?stop=' + STOP).then(setBoard).catch(() => {})
    api('/alternatives?stop=' + STOP).then(setAlts).catch(() => {})
    const t = setInterval(() => {
      api('/alternatives?stop=' + STOP).then(setAlts).catch(() => {})
    }, 30000)
    return () => clearInterval(t)
  }, [])

  const affected = (board?.departures || []).filter((r) => r.route_id === AFFECTED_ROUTE)

  return (
    <div className="wrap">
      <div className="hint">
        <b>Demo scenario</b> — the suspension is simulated; the departures, headways and
        timings below are live data, right now, at Malden Center.
      </div>

      <div className="chips" style={{ margin: '12px 0' }}>
        {STEPS.map((s, i) => (
          <button key={s} className={'chip' + (i === step ? ' active' : '')}
            style={i > step ? { opacity: 0.4 } : undefined}
            onClick={() => setStep(i)}>{i + 1}. {s}</button>
        ))}
        {step < STEPS.length - 1 &&
          <button className="chip" style={{ marginLeft: 'auto', borderColor: 'var(--cr)' }}
            onClick={() => setStep(step + 1)}>Next →</button>}
      </div>

      {step >= 0 && (
        <div className="alerts">
          <div className="alert alert-red">
            <b>Suspended</b> Haverhill Line service is suspended between Oak Grove and
            North Station due to police activity. Shuttle buses are being arranged.
            <span className="meta"> (simulated)</span>
          </div>
        </div>
      )}

      {step >= 1 && (
        <>
          <h2>Affected departures at Malden Center</h2>
          {affected.length ? (
            <table>
              <thead><tr><th>Time</th><th>Destination</th><th>Line</th><th>Status</th></tr></thead>
              <tbody>{affected.map((r, i) => (
                <tr key={i} style={{ opacity: 0.6 }}>
                  <td style={{ textDecoration: 'line-through' }}>{fmtTime(r.predicted_time || r.scheduled_time)}</td>
                  <td>{r.headsign}{r.trip_name ? ' · ' + r.trip_name : ''}</td>
                  <td><span className="dotc" style={{ background: LINE_COLORS[r.route_id] || '#888' }} /> {shortLine(r.route_id)}</td>
                  <td style={{ color: 'var(--red)', fontWeight: 600 }}>Suspended</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="empty">No upcoming Haverhill departures in the live window right now — the panel binds to whatever is scheduled.</div>}
        </>
      )}

      {step >= 2 && (
        <>
          <h2>Alternatives from this station — live</h2>
          <div className="alt-cards">
            {['subway', 'bus', 'cr'].map((mode) => {
              const rows = (alts?.by_mode?.[mode] || [])
                .filter((r) => r.route_id !== AFFECTED_ROUTE).slice(0, 4)
              return (
                <div key={mode} className="alt-card">
                  <h3>{MODE_LABEL[mode]}</h3>
                  {rows.length ? rows.map((r, i) => (
                    <div key={i} className="ticker-row">
                      <span>
                        <span className="dotc" style={{ background: r.color ? '#' + r.color : '#888' }} />{' '}
                        {r.route_id === 'Orange' ? 'Orange Line' : r.route_name} → {r.headsign}
                      </span>
                      <b>{r.mins === 0 ? 'now' : `${r.mins} min`}</b>
                    </div>
                  )) : <div className="meta">none upcoming</div>}
                </div>
              )
            })}
          </div>
          <div className="hint" style={{ marginTop: 8 }}>
            The Orange Line runs from the same platform complex to North Station — those
            headways above are real, right now.
          </div>
        </>
      )}

      {step >= 3 && (
        <>
          <h2>And riders don't have to find this page</h2>
          <div className="mock-notif">
            <div className="mock-notif-app">⚠ Commuter Rail</div>
            <b>Haverhill Line suspended</b>
            <div>Your 5:25 from Malden Center is affected. Orange Line to North Station
              departs in {alts?.by_mode?.subway?.[0]?.mins ?? 3} min from the adjacent platform.</div>
          </div>
          <div className="hint">
            Train-watch notifications are already shipped in this app (platform posted,
            delays, cancellations). As operator, this becomes a push to every affected
            ticket-holder — with the alternative included.
          </div>
        </>
      )}
    </div>
  )
}
