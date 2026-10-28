import { useCallback, useEffect, useRef, useState } from 'react'
import { dispatchNote, fetchBoard } from '@/lib/api'
import { loadPending, reconcile, savePending, type PendingNote } from '@/lib/notes'
import type { Board } from '@/lib/types'

/** board.json plus the notes this browser has sent and the bot has not confirmed yet. */
export function useBoard() {
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState<PendingNote[]>(loadPending)
  const pendingRef = useRef(pending)
  useEffect(() => {
    pendingRef.current = pending
  }, [pending])

  const updatePending = useCallback((next: PendingNote[]) => {
    pendingRef.current = next
    setPending(next)
    savePending(next)
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const b = await fetchBoard()
      setBoard(b)
      setError(null)
      updatePending(reconcile(pendingRef.current, b))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [updatePending])

  useEffect(() => {
    refresh()
  }, [refresh])

  // While notes are on their way, check every 30 s; otherwise every 5 minutes
  useEffect(() => {
    const id = window.setInterval(refresh, pending.length ? 30_000 : 300_000)
    return () => window.clearInterval(id)
  }, [refresh, pending.length])

  const sendNote = useCallback(
    async (note: Omit<PendingNote, 'at'>) => {
      await dispatchNote({ bike: note.bike, tag: note.deleteId !== undefined ? 'delete' : note.tag,
                           text: note.deleteId !== undefined ? String(note.deleteId) : note.text, lot: note.lot })
      updatePending([...pendingRef.current, { ...note, at: Date.now() }])
    },
    [updatePending],
  )

  const dropPending = useCallback(
    (p: PendingNote) => updatePending(pendingRef.current.filter((x) => x !== p)),
    [updatePending],
  )

  return { board, error, loading, refresh, pending, sendNote, dropPending }
}
