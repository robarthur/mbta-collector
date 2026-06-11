// Single source of truth for the API + shared display helpers.
export const API_BASE =
  import.meta.env.VITE_API_BASE || 'https://estimated-platform.robarthur1.workers.dev/api/v1'

export async function api(path) {
  const r = await fetch(API_BASE + path)
  if (!r.ok) throw new Error('HTTP ' + r.status)
  return r.json()
}

export const LINE_COLORS = {
  'CR-Fitchburg': '#e6794b', 'CR-Lowell': '#5fb0e6', 'CR-Haverhill': '#b06be0',
  'CR-Newburyport': '#e6c84b', 'CR-Worcester': '#5fd896', 'CR-Franklin': '#e65f8a',
  'CR-Needham': '#9ad14b', 'CR-Providence': '#e64b4b', 'CR-Fairmount': '#4be6d0',
  'CR-Greenbush': '#8a9ae6', 'CR-Kingston': '#d68a5f', 'CR-NewBedford': '#c0e64b',
  'CR-Foxboro': '#e6b0d0',
}

export const shortLine = (r) => (r || '').replace('CR-', '')

// Hex (not CSS vars) — these feed Leaflet SVG marker attributes, where var() won't resolve.
export const DELAY_COLORS = { grey: '#5a6072', blue: '#3b82f6', green: '#1f8f4e', amber: '#d99a1e', red: '#e2706b' }
export function delayColor(s) {
  if (s == null) return DELAY_COLORS.grey
  if (s < 0) return DELAY_COLORS.blue
  if (s <= 120) return DELAY_COLORS.green
  if (s <= 300) return DELAY_COLORS.amber
  return DELAY_COLORS.red
}

export function fmtDelay(s) {
  if (s == null) return '—'
  const m = s / 60
  return (m >= 0 ? '+' : '') + m.toFixed(1) + 'm'
}

export function fmtTime(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}

export const EFFECT_LABEL = {
  CANCELLATION: 'Cancelled', NO_SERVICE: 'No service', TRACK_CHANGE: 'Track change',
  DELAY: 'Delayed', SUSPENSION: 'Suspended', SHUTTLE: 'Shuttle', DETOUR: 'Detour',
  SCHEDULE_CHANGE: 'Schedule change', SERVICE_CHANGE: 'Service change',
  STATION_ISSUE: 'Station issue', SNOW_ROUTE: 'Snow route',
}
