import { useEffect, useState } from 'react'

/** Current time in seconds, re-rendering every minute so "12 min ago" stays true. */
export function useNow() {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), 60_000)
    return () => window.clearInterval(id)
  }, [])
  return now
}
