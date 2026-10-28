import { createContext, useContext } from 'react'
import type { NoteInput } from '@/hooks/useBoard'
import type { PendingNote } from './notes'
import type { Board } from './types'

export interface AppState {
  board: Board | null
  pending: PendingNote[]
  sendNote: (note: NoteInput, replaces?: PendingNote) => Promise<void>
  dropPending: (p: PendingNote) => void
  openSettings: () => void
}

export const AppContext = createContext<AppState | null>(null)

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp outside AppContext')
  return ctx
}
