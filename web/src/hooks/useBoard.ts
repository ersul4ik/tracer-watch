import { useCallback, useEffect, useRef, useState } from 'react'
import { dispatchNote, fetchBoard } from '@/lib/api'
import {
  MAX_TRIES,
  RESEND_AFTER_MS,
  isFailed,
  loadPending,
  reconcile,
  savePending,
  type PendingNote,
} from '@/lib/notes'
import type { Board } from '@/lib/types'

export type NoteInput = Pick<PendingNote, 'bike' | 'tag' | 'text' | 'lot' | 'deleteId'>

function dispatch(note: NoteInput) {
  const del = note.deleteId !== undefined
  return dispatchNote({ bike: note.bike, tag: del ? 'delete' : note.tag, text: del ? String(note.deleteId) : note.text, lot: note.lot })
}

/** board.json plus the notes this browser has sent and the bot has not confirmed yet. */
export function useBoard() {
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState<PendingNote[]>(loadPending)
  const pendingRef = useRef(pending)
  const boardRef = useRef(board)

  const updatePending = useCallback((next: PendingNote[]) => {
    pendingRef.current = next
    setPending(next)
    savePending(next)
  }, [])

  // Resend notes that are still unconfirmed after a while: their run may have been dropped
  const resendStale = useCallback(async () => {
    const now = Date.now()
    for (const p of pendingRef.current) {
      if (p.tries >= MAX_TRIES || isFailed(p, now) || now - p.at < RESEND_AFTER_MS * p.tries) continue
      try {
        await dispatch(p)
        updatePending(pendingRef.current.map((x) => (x === p ? { ...x, tries: x.tries + 1 } : x)))
      } catch {
        /* the next refresh tries again; the timeout turns it into a visible failure */
      }
    }
  }, [updatePending])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const b = await fetchBoard()
      boardRef.current = b
      setBoard(b)
      setError(null)
      updatePending(reconcile(pendingRef.current, b))
      await resendStale()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [updatePending, resendStale])

  useEffect(() => {
    refresh()
  }, [refresh])

  // While notes are on their way, check every 30 s; otherwise every 5 minutes
  const waiting = pending.some((p) => !isFailed(p, Date.now()))
  useEffect(() => {
    const id = window.setInterval(refresh, waiting ? 30_000 : 300_000)
    return () => window.clearInterval(id)
  }, [refresh, waiting])

  /** Sends a note; on success it shows as pending until the bot confirms it. Throws on failure. */
  const sendNote = useCallback(
    async (note: NoteInput, replaces?: PendingNote) => {
      await dispatch(note)
      const known = (boardRef.current?.notes[note.bike] ?? []).map((n) => n.id)
      const rest = pendingRef.current.filter((x) => x !== replaces)
      updatePending([...rest, { ...note, at: Date.now(), tries: 1, known }])
    },
    [updatePending],
  )

  const dropPending = useCallback(
    (p: PendingNote) => updatePending(pendingRef.current.filter((x) => x !== p)),
    [updatePending],
  )

  return { board, error, loading, refresh, pending, sendNote, dropPending }
}
