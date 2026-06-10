import { api } from './api'

// "Watch this train": localStorage-backed watches checked against fresh /station data.
// Fires one-shot OS notifications (platform posted / >5 min late / cancelled) while the
// app or tab is open. True app-closed delivery needs Web Push (a later tier).

const KEY = 'watches-v1'
const DELAY_NOTIFY_S = 300         // notify once when a watched train goes >5 min late
const EXPIRE_AFTER_MS = 30 * 60 * 1000  // drop watches 30 min past their departure

export const supported = typeof window !== 'undefined' && 'Notification' in window

function load() {
  try { return JSON.parse(localStorage.getItem(KEY)) || {} } catch { return {} }
}
function save(w) { localStorage.setItem(KEY, JSON.stringify(w)) }

export function getWatches() { return load() }
export function isWatched(tripId) { return Boolean(load()[tripId]) }

export function addWatch(row, stop) {
  const w = load()
  w[row.trip_id] = {
    trip_id: row.trip_id, stop,
    trip_name: row.trip_name, headsign: row.headsign, route_id: row.route_id,
    scheduled_time: row.scheduled_time || row.predicted_time,
    notified: {},
  }
  save(w)
}

export function removeWatch(tripId) {
  const w = load()
  delete w[tripId]
  save(w)
}

export function prune() {
  const w = load()
  const cutoff = Date.now() - EXPIRE_AFTER_MS
  let changed = false
  for (const id of Object.keys(w)) {
    const t = Date.parse(w[id].scheduled_time || '')
    if (!t || t < cutoff) { delete w[id]; changed = true }
  }
  if (changed) save(w)
  return w
}

export async function requestPermission() {
  if (!supported) return 'unsupported'
  if (Notification.permission === 'granted') return 'granted'
  try { return await Notification.requestPermission() } catch { return 'denied' }
}

async function notify(title, body, tag) {
  if (!supported || Notification.permission !== 'granted') return
  // Android Chrome has no Notification constructor; go through the PWA service worker.
  try {
    const reg = await navigator.serviceWorker?.ready
    if (reg) { await reg.showNotification(title, { body, tag }); return }
  } catch { /* fall through to the constructor */ }
  try { new Notification(title, { body, tag }) } catch { /* unsupported context */ }
}

// Check a fresh departures board against the watches for this stop; fire at most one
// notification per condition per watch and persist the notified flags.
export function checkBoard(stop, departures) {
  const w = load()
  let changed = false
  for (const r of departures || []) {
    const watch = r.trip_id && w[r.trip_id]
    if (!watch || watch.stop !== stop) continue
    const label = `Train ${r.trip_name || ''} to ${r.headsign || ''}`.trim()
    if (r.confirmed_track && !watch.notified.platform) {
      notify(`Platform ${r.confirmed_track}`, `${label} boards from platform ${r.confirmed_track}`,
        r.trip_id + ':platform')
      watch.notified.platform = true; changed = true
    }
    if ((r.alert_effect === 'CANCELLATION' || r.alert_effect === 'NO_SERVICE') && !watch.notified.cancel) {
      notify('Cancelled', `${label} has been cancelled`, r.trip_id + ':cancel')
      watch.notified.cancel = true; changed = true
    }
    if (r.delay_s > DELAY_NOTIFY_S && !watch.notified.delay) {
      notify(`Running ~${Math.round(r.delay_s / 60)} min late`, label, r.trip_id + ':delay')
      watch.notified.delay = true; changed = true
    }
  }
  if (changed) save(w)
}

// Poll every watched stop (the app-level loop: watches fire from any view).
export async function checkAll() {
  const w = prune()
  const stops = [...new Set(Object.values(w).map((x) => x.stop))]
  for (const stop of stops) {
    try {
      const d = await api('/station?stop=' + encodeURIComponent(stop))
      checkBoard(stop, d.departures)
    } catch { /* transient; next tick retries */ }
  }
}
