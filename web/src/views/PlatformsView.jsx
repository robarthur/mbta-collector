import { useEffect, useState } from 'react'
import { api, shortLine, fmtTime } from '../api'

const STATIONS = [['north', 'North Station'], ['south', 'South Station'], ['backbay', 'Back Bay']]
const ZONE_HINT = {
  north: 'Predicted zone: Eastern Route (Newburyport/Rockport, Haverhill) → east tracks 1–5; Fitchburg & Lowell → west 6–10 (Fitchburg usually 9/10). Exact track is set late by dispatch — only the zone is reliably predictable here.',
  south: 'Predicted band: Worcester→1–2, Needham→3–4, Providence→5–8, Fairmount→10, Old Colony (Greenbush/Kingston) + NewBedford→11–13. ~87% land within ±1 track of their usual.',
  backbay: 'Through-station: platforms come from the schedule, so the track is usually known well in advance.',
}

export default function PlatformsView() {
  const [station, setStation] = useState('north')
  const [board, setBoard] = useState({ occupancy: {} })
  const [predict, setPredict] = useState({ inbound: [] })
  const [events, setEvents] = useState([])

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [b, p, e] = await Promise.all([
          api('/board?station=' + station), api('/predict?station=' + station), api('/events'),
        ])
        if (active) { setBoard(b); setPredict(p); setEvents(e) }
      } catch { /* keep last */ }
    }
    load()
    const t = setInterval(load, 30000)
    return () => { active = false; clearInterval(t) }
  }, [station])

  const occ = board.occupancy || {}
  return (
    <div className="wrap">
      <div className="chips">
        {STATIONS.map(([k, name]) => (
          <button key={k} className={'chip' + (k === station ? ' active' : '')}
            onClick={() => setStation(k)}>{name}</button>
        ))}
      </div>
      <div className="hint">{ZONE_HINT[station]}</div>

      <h2>Platform occupancy</h2>
      {Object.keys(occ).length ? (
        <div className="grid">{Object.keys(occ).map((t) => {
          const who = occ[t]
          return (
            <div key={t} className={'cell' + (who ? ' occ' : '')}>
              <div className="trk">Track</div><div className="num">{t}</div>
              <div className="who">{who ? <>{shortLine(who.route)}<br />veh {who.vehicle || ''}</> : 'free'}</div>
            </div>
          )
        })}</div>
      ) : <div className="empty">No track data.</div>}

      <h2>Inbound trains</h2>
      {(predict.inbound || []).length ? (
        <table><thead><tr><th>Arrival</th><th>Route</th><th>Status</th><th>Track</th><th>Predicted</th></tr></thead>
          <tbody>{predict.inbound.map((r, i) => (
            <tr key={i}>
              <td>{fmtTime(r.arrival_time)}</td><td>{shortLine(r.route)}</td><td>{r.status || '—'}</td>
              <td>{r.track_known
                ? <span className="pill" style={{ background: 'rgba(31,143,78,.2)', color: '#5fd896' }}>Track {r.actual_track}</span>
                : <span className="pill" style={{ background: 'rgba(90,96,114,.25)', color: '#aab1bf' }}>unknown</span>}</td>
              <td>{!r.track_known && r.prediction
                ? <><b>Track {r.prediction.predicted_track}</b> <span className="meta">{r.prediction.confidence}% · {r.prediction.basis} (n={r.prediction.n_samples})</span></>
                : '—'}</td>
            </tr>
          ))}</tbody></table>
      ) : <div className="empty">No inbound trains.</div>}

      <h2>Recent platform resolutions (all stations)</h2>
      {events.length ? (
        <table><thead><tr><th>Resolved</th><th>Station</th><th>Route</th><th>Track</th><th>How</th></tr></thead>
          <tbody>{events.slice(0, 15).map((r, i) => (
            <tr key={i}><td>{fmtTime(r.resolved_ts)}</td><td>{r.station}</td><td>{shortLine(r.route_id)}</td>
              <td>{r.resolved_track}</td><td>{r.resolved_via === 'vehicle_stopped_at' ? 'berthed' : 'board'}</td></tr>
          ))}</tbody></table>
      ) : <div className="empty">No resolutions yet.</div>}
    </div>
  )
}
