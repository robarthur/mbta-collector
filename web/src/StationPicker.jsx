import { useState, useRef, useEffect } from 'react'

// Major hubs pinned to the top (also the stations where platform prediction works).
const MAJOR = ['place-north', 'place-sstat', 'place-bbsta']

// Combobox: type to filter the 148 stations, or focus the empty field to browse the full
// list (major hubs first) like a dropdown. Selection is reported via onChange(stopId).
export default function StationPicker({ stops, value, onChange }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const wrapRef = useRef(null)
  const selectedName = stops.find((s) => s.id === value)?.name || ''

  useEffect(() => {
    const onDoc = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const q = query.trim().toLowerCase()
  let list
  if (!q) {
    const major = MAJOR.map((id) => stops.find((s) => s.id === id)).filter(Boolean)
    list = [...major, ...stops.filter((s) => !MAJOR.includes(s.id))]
  } else {
    list = stops.filter((s) => s.name.toLowerCase().includes(q)).sort((a, b) => {
      const am = MAJOR.includes(a.id), bm = MAJOR.includes(b.id)
      if (am !== bm) return am ? -1 : 1                                    // hubs first
      const as = a.name.toLowerCase().startsWith(q), bs = b.name.toLowerCase().startsWith(q)
      if (as !== bs) return as ? -1 : 1                                    // prefix matches first
      return a.name.localeCompare(b.name)
    })
  }
  const majorLen = q ? 0 : MAJOR.length
  list = list.slice(0, 60)

  const pick = (s) => { onChange(s.id); setQuery(''); setOpen(false) }

  return (
    <div className="combo" ref={wrapRef}>
      <input
        className="combo-input"
        value={open ? query : selectedName}
        placeholder="Search station…"
        onFocus={() => { setOpen(true); setQuery(''); setHi(0) }}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setHi(0) }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, list.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)) }
          else if (e.key === 'Enter') { e.preventDefault(); if (list[hi]) pick(list[hi]) }
          else if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
        }}
      />
      {open && (
        <ul className="combo-list">
          {list.length ? list.map((s, i) => (
            <li key={s.id}
              className={'combo-item' + (i === hi ? ' hi' : '') + (s.id === value ? ' sel' : '')
                + (i < majorLen ? ' major' : '') + (i === majorLen && majorLen ? ' divide' : '')}
              onMouseEnter={() => setHi(i)}
              onMouseDown={(e) => { e.preventDefault(); pick(s) }}>
              {s.name}
            </li>
          )) : <li className="combo-item meta">No match</li>}
        </ul>
      )}
    </div>
  )
}
