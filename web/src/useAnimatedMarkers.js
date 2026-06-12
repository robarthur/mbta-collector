import { useEffect, useRef } from 'react'

// Imperative marker animation shared by the live map and replay: one rAF loop asks
// getPositions(nowMs) for a Map(id -> [lat,lng]) and setLatLng's the registered Leaflet
// layers directly — no React re-render per frame (cheap with the canvas renderer).
export function useAnimatedMarkers(getPositions) {
  const markers = useRef(new Map())
  const getRef = useRef(getPositions)
  getRef.current = getPositions

  useEffect(() => {
    let raf
    const step = () => {
      const pos = getRef.current(performance.now())
      if (pos) {
        for (const [id, p] of pos) {
          const m = markers.current.get(id)
          if (m && p) m.setLatLng(p)
        }
      }
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [])

  // ref-callback factory: <CircleMarker ref={registerRef(id)} ...>
  return (id) => (m) => {
    if (m) markers.current.set(id, m)
    else markers.current.delete(id)
  }
}
