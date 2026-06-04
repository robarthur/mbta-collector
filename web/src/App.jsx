import { useEffect, useState } from 'react'
import { NavLink, Routes, Route, Navigate } from 'react-router-dom'
import { api, fmtTime } from './api'
import MapView from './views/MapView.jsx'
import LinesView from './views/LinesView.jsx'
import PlatformsView from './views/PlatformsView.jsx'

export default function App() {
  const [health, setHealth] = useState(null)
  useEffect(() => {
    const load = () => api('/health').then(setHealth).catch(() => {})
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  return (
    <>
      <header>
        <h1><span className="dot">●</span> MBTA Commuter Rail</h1>
        <span className="meta">
          {health
            ? `${health.track_events} platform events · ${health.snapshots} snapshots · last ${fmtTime(health.last_poll_ts)}`
            : 'loading…'}
        </span>
        <nav>
          <NavLink to="/map">Map</NavLink>
          <NavLink to="/lines">Lines</NavLink>
          <NavLink to="/platforms">Platforms</NavLink>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Navigate to="/map" replace />} />
        <Route path="/map" element={<MapView />} />
        <Route path="/lines" element={<LinesView />} />
        <Route path="/platforms" element={<PlatformsView />} />
        <Route path="*" element={<Navigate to="/map" replace />} />
      </Routes>
    </>
  )
}
