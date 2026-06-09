import { useRegisterSW } from 'virtual:pwa-register/react'

// Shows a small banner when a new deploy is available, and polls for updates so a
// long-open tab / installed PWA notices new versions without a manual cache clear.
export default function ReloadPrompt() {
  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, r) {
      if (r) setInterval(() => r.update(), 60_000)  // check for a new SW every minute
    },
  })

  if (!needRefresh) return null
  return (
    <div className="update-toast">
      <span>New version available.</span>
      <button onClick={() => updateServiceWorker(true)}>Reload</button>
    </div>
  )
}
