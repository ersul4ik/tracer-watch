import type { Board } from './types'

export const REPO = 'ersul4ik/tracer-watch'
const API_BOARD = `https://api.github.com/repos/${REPO}/contents/board.json?ref=state`
const RAW_BOARD = `https://raw.githubusercontent.com/${REPO}/state/board.json`
const DISPATCH = `https://api.github.com/repos/${REPO}/actions/workflows/watch.yml/dispatches`
const TOKEN_KEY = 'tracer-watch:token'

// Browser storage can be missing or throw (private mode, blocked site data)
function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function getToken(): string {
  try {
    return storage()?.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setToken(token: string) {
  try {
    if (token) storage()?.setItem(TOKEN_KEY, token.trim())
    else storage()?.removeItem(TOKEN_KEY)
  } catch {
    /* the token then lives only for this visit */
  }
}

/**
 * The contents API is fresh but rate-limited to 60 requests an hour without a token;
 * raw.githubusercontent.com is unlimited but cached for up to 5 minutes. Try the fresh one first.
 */
export async function fetchBoard(): Promise<Board> {
  const local = import.meta.env.VITE_BOARD_URL as string | undefined
  if (local) return (await fetch(local, { cache: 'no-store' })).json()
  const token = getToken()
  try {
    const res = await fetch(API_BOARD, {
      cache: 'no-store',
      headers: { Accept: 'application/vnd.github.raw+json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    if (res.ok) return res.json()
  } catch {
    /* fall through to raw */
  }
  const res = await fetch(`${RAW_BOARD}?t=${Date.now()}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Не удалось загрузить данные: ${res.status}`)
  return res.json()
}

export interface NoteRequest {
  bike: string
  tag: string
  text: string
  lot: string
}

/** A note goes to the bot as a workflow run; it lands in board.json within about a minute. */
export async function dispatchNote(note: NoteRequest) {
  const token = getToken()
  if (!token) throw new Error('Нужен токен GitHub — его можно добавить в настройках')
  const res = await fetch(DISPATCH, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ref: 'main',
      inputs: { note_key: note.bike, note_tag: note.tag, note_text: note.text, note_lot: note.lot },
    }),
  })
  if (res.status === 401 || res.status === 403) throw new Error('GitHub не принял токен: проверь, что у него есть Actions: Read and write')
  if (res.status === 404) throw new Error('GitHub не видит репозиторий с этим токеном: выбери tracer-watch в его настройках')
  if (!res.ok) throw new Error(`GitHub ответил ${res.status}`)
}
