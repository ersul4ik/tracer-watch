import { useState } from 'react'
import { Loader2, PenLine, RotateCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useNow } from '@/hooks/useNow'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { getToken } from '@/lib/api'
import { useApp } from '@/lib/context'
import { dateTime } from '@/lib/format'
import { PENDING_TIMEOUT_MS, TAGS, noteLabel, notesFor } from '@/lib/notes'
import { cn } from '@/lib/utils'

/** Notes on a bike as small chips, including the ones still on their way to the bot. */
export function NoteChips({ bike, className }: { bike: string; className?: string }) {
  const { board, pending, sendNote, dropPending } = useApp()
  const now = useNow()
  const notes = notesFor(board, bike)
  const mine = pending.filter((p) => p.bike === bike)
  const deleting = new Set(mine.filter((p) => p.deleteId !== undefined).map((p) => p.deleteId))
  if (!notes.length && !mine.length) return null
  return (
    <div className={cn('flex flex-wrap gap-1.5', className)}>
      {notes.map((n) => (
        <span
          key={n.id}
          title={`${dateTime(n.created_at)} · ${n.source === 'telegram' ? 'из Telegram' : 'с сайта'}`}
          className={cn(
            'rounded-md bg-accent px-2 py-0.5 text-xs text-accent-foreground',
            deleting.has(n.id) && 'line-through opacity-50',
          )}
        >
          {noteLabel(n)}
        </span>
      ))}
      {mine
        .filter((p) => p.deleteId === undefined)
        .map((p) => {
          const failed = now * 1000 - p.at > PENDING_TIMEOUT_MS
          return (
            <span
              key={p.at}
              className={cn(
                'inline-flex items-center gap-1 rounded-md border border-dashed px-2 py-0.5 text-xs',
                failed ? 'border-bad text-bad' : 'text-muted-foreground',
              )}
            >
              {failed ? 'не сохранилось: ' : <Loader2 className="size-3 animate-spin" />}
              {noteLabel(p)}
              {failed && (
                <>
                  <button
                    className="ml-1 underline"
                    onClick={() => {
                      dropPending(p)
                      sendNote({ bike: p.bike, tag: p.tag, text: p.text, lot: p.lot }).catch(() => {})
                    }}
                  >
                    <RotateCw className="size-3" aria-label="Повторить" />
                  </button>
                  <button onClick={() => dropPending(p)}>
                    <X className="size-3" aria-label="Убрать" />
                  </button>
                </>
              )}
            </span>
          )
        })}
    </div>
  )
}

/** Button + dialog: leave a quick tag and/or a comment on a bike. */
export function NoteButton({ bike, lot, title }: { bike: string; lot: string; title: string }) {
  const { board, pending, sendNote, openSettings } = useApp()
  const [open, setOpen] = useState(false)
  const [tag, setTag] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const notes = notesFor(board, bike)
  const deleting = new Set(pending.filter((p) => p.bike === bike && p.deleteId !== undefined).map((p) => p.deleteId))
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
      await sendNote({ bike, tag: '', text: '', lot, deleteId: id })
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
            <DialogDescription>{title}. Метка привязана к раме: её будет видно и после перевыставления.</DialogDescription>
          </DialogHeader>

          {notes.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {notes.map((n) => (
                <li key={n.id} className="flex items-start justify-between gap-2 rounded-md bg-muted px-2.5 py-1.5 text-sm">
                  <span className={cn(deleting.has(n.id) && 'line-through opacity-50')}>
                    {noteLabel(n)}
                    <span className="ml-2 text-xs text-muted-foreground">{dateTime(n.created_at)}</span>
                  </span>
                  {hasToken && !deleting.has(n.id) && (
                    <button className="text-muted-foreground hover:text-foreground" onClick={() => remove(n.id)}>
                      <X className="size-4" aria-label="Удалить метку" />
                    </button>
                  )}
                </li>
              ))}
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
