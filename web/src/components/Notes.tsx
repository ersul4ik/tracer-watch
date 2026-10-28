import { useState } from 'react'
import { Loader2, PenLine, RotateCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useNow } from '@/hooks/useNow'
import { getToken } from '@/lib/api'
import { useApp } from '@/lib/context'
import { dateTime } from '@/lib/format'
import { TAGS, isFailed, noteLabel, notesFor, type PendingNote } from '@/lib/notes'
import type { Note } from '@/lib/types'
import { cn } from '@/lib/utils'

const chip = 'max-w-full rounded-md px-2 py-0.5 text-xs [overflow-wrap:anywhere]'

function sourceTag(n: Note) {
  return n.source === 'telegram' ? ' · TG' : ''
}

/** A failed note or deletion: retry or dismiss, with buttons big enough for a finger. */
function FailedChip({ p, label }: { p: PendingNote; label: string }) {
  const { sendNote, dropPending } = useApp()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <span className={cn(chip, 'inline-flex flex-wrap items-center gap-1 border border-dashed border-bad text-bad')}>
      {label}
      <button
        className="inline-flex size-7 items-center justify-center rounded-md hover:bg-bad-soft"
        aria-label="Отправить ещё раз"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          setError(null)
          try {
            await sendNote({ bike: p.bike, tag: p.tag, text: p.text, lot: p.lot, deleteId: p.deleteId }, p)
          } catch (e) {
            setError(e instanceof Error ? e.message : String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : <RotateCw className="size-4" />}
      </button>
      <button
        className="inline-flex size-7 items-center justify-center rounded-md hover:bg-bad-soft"
        aria-label="Убрать"
        onClick={() => dropPending(p)}
      >
        <X className="size-4" />
      </button>
      {error && <span className="basis-full">{error}</span>}
    </span>
  )
}

/** Notes on a bike as small chips, including the ones still on their way to the bot. */
export function NoteChips({ bike, className }: { bike: string; className?: string }) {
  const { board, pending } = useApp()
  const now = useNow() * 1000
  const notes = notesFor(board, bike)
  const mine = pending.filter((p) => p.bike === bike)
  const deleting = new Map(mine.filter((p) => p.deleteId !== undefined).map((p) => [p.deleteId, p]))
  if (!notes.length && !mine.length) return null
  return (
    <div className={cn('flex min-w-0 flex-wrap gap-1.5', className)}>
      {notes.map((n) => {
        const del = deleting.get(n.id)
        if (del && isFailed(del, now)) return <FailedChip key={n.id} p={del} label={`не удалилось: ${noteLabel(n)}`} />
        return (
          <span
            key={n.id}
            title={`${dateTime(n.created_at)} · ${n.source === 'telegram' ? 'из Telegram' : 'с сайта'}`}
            className={cn(chip, 'bg-accent text-accent-foreground', del && 'line-through opacity-50')}
          >
            {noteLabel(n)}
            <span className="opacity-60">{sourceTag(n)}</span>
          </span>
        )
      })}
      {mine
        .filter((p) => p.deleteId === undefined)
        .map((p) =>
          isFailed(p, now) ? (
            <FailedChip key={p.at} p={p} label={`не сохранилось: ${noteLabel(p)}`} />
          ) : (
            <span key={p.at} className={cn(chip, 'inline-flex items-center gap-1 border border-dashed text-muted-foreground')}>
              <Loader2 className="size-3 shrink-0 animate-spin" />
              {noteLabel(p)}
            </span>
          ),
        )}
    </div>
  )
}

/** Button + dialog: leave a quick tag and/or a comment on a bike. */
export function NoteButton({ bike, lot, title }: { bike: string; lot: string; title: string }) {
  const { board, pending, sendNote, openSettings } = useApp()
  const now = useNow() * 1000
  const [open, setOpen] = useState(false)
  const [tag, setTag] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const notes = notesFor(board, bike)
  const deleting = new Map(
    pending.filter((p) => p.bike === bike && p.deleteId !== undefined).map((p) => [p.deleteId, p]),
  )
  const hasToken = Boolean(getToken())

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await sendNote({ bike, tag, text: text.trim(), lot })
      setTag('')
      setText('')
      setOpen(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: number) {
    setError(null)
    try {
      await sendNote({ bike, tag: '', text: '', lot, deleteId: id }, deleting.get(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <PenLine data-icon="inline-start" />
        Метка
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Метка</DialogTitle>
            <DialogDescription>{title}. Метка привязана к мотоциклу: её будет видно и после перевыставления.</DialogDescription>
          </DialogHeader>

          {notes.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {notes.map((n) => {
                const del = deleting.get(n.id)
                const inFlight = del && !isFailed(del, now)
                return (
                  <li key={n.id} className="flex items-center justify-between gap-2 rounded-md bg-muted py-1 pr-1 pl-2.5 text-sm">
                    <span className={cn('min-w-0 [overflow-wrap:anywhere]', inFlight && 'line-through opacity-50')}>
                      {noteLabel(n)}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {dateTime(n.created_at)}
                        {n.source === 'telegram' ? ' · из Telegram' : ''}
                      </span>
                    </span>
                    {hasToken && !inFlight && (
                      <button
                        className="inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground"
                        aria-label="Удалить метку"
                        onClick={() => remove(n.id)}
                      >
                        <X className="size-4" />
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}

          {hasToken ? (
            <div className="flex flex-col gap-3">
              <ToggleGroup type="single" value={tag} onValueChange={setTag} variant="outline" size="sm" className="flex-wrap">
                {Object.entries(TAGS).map(([id, t]) => (
                  <ToggleGroupItem key={id} value={id} aria-label={t.label}>
                    {t.icon} {t.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <Textarea
                id={`note-${bike}`}
                placeholder="Комментарий, например: вилка течёт, дорого для такого пробега"
                value={text}
                maxLength={500}
                onChange={(e) => setText(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Метку сохранит бот, на сайте она появится примерно через минуту. Ещё её можно оставить в Telegram: ответь
                текстом на сообщение бота о лоте.
              </p>
            </div>
          ) : (
            <div className="rounded-md bg-warn-soft p-3 text-sm">
              Чтобы ставить метки с сайта, добавь токен GitHub в настройках. Пока можно ответить текстом на сообщение бота о
              лоте в Telegram, бот запишет это как метку.
              <Button variant="link" className="h-auto p-0 pl-1" onClick={() => { setOpen(false); openSettings() }}>
                Открыть настройки
              </Button>
            </div>
          )}

          {error && <p className="text-sm text-bad">{error}</p>}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Закрыть
            </Button>
            {hasToken && (
              <Button onClick={save} disabled={busy || (!tag && !text.trim())}>
                {busy && <Loader2 className="animate-spin" data-icon="inline-start" />}
                Сохранить
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
