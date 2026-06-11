import { useRegisterSW } from 'virtual:pwa-register/react'

// Silent PWA updates: autoUpdate applies new deploys on detection; the 60s poll is what
// lets a long-open tab notice them (the default only checks on page load). Renders nothing.
export default function SWUpdate() {
  useRegisterSW({
    onRegisteredSW(_swUrl, r) {
      if (r) setInterval(() => r.update(), 60_000)
    },
  })
  return null
}
