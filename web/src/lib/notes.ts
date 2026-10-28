import type { Board, Note } from './types'

export const TAGS: Record<string, { label: string; icon: string; hides: boolean }> = {
  seen: { label: 'посмотрел', icon: '👀', hides: false },
  price: { label: 'дорого', icon: '💴', hides: true },
  repair: { label: 'ремонт', icon: '🔧', hides: true },
  mileage: { label: 'пробег', icon: '📏', hides: true },
  like: { label: 'интересно', icon: '⭐', hides: false },
}

/** A note sent from this browser that the bot has not confirmed in board.json yet. */
export interface PendingNote {
  bike: string
  tag: string
  text: string
  lot: string
  at: number // ms
  deleteId?: number
}

const KEY = 'tracer-watch:pending'
// After this long without confirmation the note is shown as failed, with a retry button
export const PENDING_TIMEOUT_MS = 6 * 60 * 1000

export function loadPending(): PendingNote[] {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? '[]')
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

/** Drops pending notes the bot has already stored (or deleted). */
export function reconcile(pending: PendingNote[], board: Board): PendingNote[] {
  return pending.filter((p) => {
    const notes = board.notes[p.bike] ?? []
    if (p.deleteId !== undefined) return notes.some((n) => n.id === p.deleteId)
    return !notes.some((n) => n.tag === p.tag && (n.text ?? '') === p.text && n.created_at * 1000 >= p.at - 120_000)
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
