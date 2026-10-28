import type { Board, Note } from './types'

export const TAGS: Record<string, { label: string; icon: string; hides: boolean }> = {
  seen: { label: 'посмотрел', icon: '👀', hides: false },
  price: { label: 'дорого', icon: '💴', hides: true },
  repair: { label: 'ремонт', icon: '🔧', hides: true },
  mileage: { label: 'пробег', icon: '📏', hides: true },
  like: { label: 'интересно', icon: '⭐', hides: false },
}

export const HIDING_LABELS = Object.values(TAGS)
  .filter((t) => t.hides)
  .map((t) => `«${t.label}»`)
  .join(', ')

/** A note sent from this browser that the bot has not confirmed in board.json yet. */
export interface PendingNote {
  bike: string
  tag: string
  text: string
  lot: string
  at: number // ms, first send
  tries: number // sends so far
  known: number[] // note ids the bike already had when this was sent
  deleteId?: number
}

const KEY = 'tracer-watch:pending'
// GitHub keeps one queued run per concurrency group, so a note run can be replaced by the next
// ping. Resend after this long without confirmation; the bot ignores a duplicate of a recent note.
export const RESEND_AFTER_MS = 150_000
export const MAX_TRIES = 3
// After this long without confirmation the note is shown as failed, with a retry button
export const PENDING_TIMEOUT_MS = 10 * 60 * 1000

export function loadPending(): PendingNote[] {
  try {
    const list = JSON.parse(window.localStorage.getItem(KEY) ?? '[]') as PendingNote[]
    return list.map((p) => ({ ...p, tries: p.tries ?? 1, known: p.known ?? [] }))
  } catch {
    return []
  }
}

export function savePending(list: PendingNote[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    /* kept in memory only */
  }
}

export const isFailed = (p: PendingNote, nowMs: number) => nowMs - p.at > PENDING_TIMEOUT_MS

/**
 * Drops pending notes the bot has already stored (or deleted). A stored note is one with the same
 * tag and text whose id the bike did not have when it was sent: no clock comparison, so a phone
 * clock that is off does not matter.
 */
export function reconcile(pending: PendingNote[], board: Board): PendingNote[] {
  return pending.filter((p) => {
    const notes = board.notes[p.bike] ?? []
    if (p.deleteId !== undefined) return notes.some((n) => n.id === p.deleteId)
    return !notes.some((n) => n.tag === p.tag && (n.text ?? '') === p.text && !p.known.includes(n.id))
  })
}

export function notesFor(board: Board | null, bike: string): Note[] {
  return board?.notes[bike] ?? []
}

export function noteLabel(n: { tag: string; text: string }) {
  const t = TAGS[n.tag]
  return [t ? `${t.icon} ${t.label}` : n.tag, n.text].filter(Boolean).join(' — ')
}

/** A bike is hidden by the "hide marked" filter when any of its notes carries a hiding tag. */
export function isHidden(board: Board | null, bike: string) {
  return notesFor(board, bike).some((n) => TAGS[n.tag]?.hides)
}
