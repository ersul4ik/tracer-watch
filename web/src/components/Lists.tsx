import { ExternalLink } from 'lucide-react'
import { NoteButton, NoteChips } from '@/components/Notes'
import { Photo } from '@/components/LotCard'
import { useNow } from '@/hooks/useNow'
import { useApp } from '@/lib/context'
import { dateTime, daysLeft, daysUntil, grade, joinParts, km, shortDate, yen, yenShort } from '@/lib/format'
import { HIDING_LABELS, isHidden } from '@/lib/notes'
import type { HistoryItem, Lot, Watched } from '@/lib/types'
import { cn } from '@/lib/utils'

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">{children}</p>
}

function Ext({ href, children }: { href: string | null; children: React.ReactNode }) {
  if (!href) return <>{children}</>
  return (
    <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline">
      {children}
      <ExternalLink className="size-3 opacity-60" />
    </a>
  )
}

/** Every Tracer on sale, matching or not, with the reason it was skipped. */
export function OnSale({ lots, hideMarked }: { lots: Lot[]; hideMarked: boolean }) {
  const { board } = useApp()
  const shown = lots.filter((l) => !hideMarked || !isHidden(board, l.bike))
  if (!shown.length)
    return (
      <Empty>
        {lots.length
          ? `Все лоты в продаже скрыты: у них метки ${HIDING_LABELS}. Выключи фильтр, чтобы их увидеть.`
          : 'Сейчас нет Tracer в продаже.'}
      </Empty>
    )
  return (
    <ul className="flex flex-col divide-y rounded-xl border bg-card">
      {shown.map((l) => (
        <li key={l.key} className="flex gap-3 p-3">
          <Photo src={l.photo} alt={l.model} className="size-16 shrink-0 rounded-md sm:size-20" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-medium">
                <Ext href={l.links[0]?.url ?? null}>
                  {l.model} · {l.year ?? '?'}
                </Ext>
              </span>
              <span className="tabular text-sm">
                {l.start ? `старт ${yenShort(l.start)}` : 'старт ?'}
                {l.estimate ? ` · обычно ~${yenShort(l.estimate.median)}` : ''}
              </span>
            </div>
            <p className="tabular text-xs text-muted-foreground">
              {joinParts(`оценка ${grade(l.rank)}`, km(l.mileage), l.auction, daysLeft(daysUntil(l.date_iso)), l.date && `(${shortDate(l.date)})`)}
            </p>
            <p className={cn('text-xs [overflow-wrap:anywhere]', l.reason ? 'text-muted-foreground' : 'font-medium text-ok')}>
              {l.reason ? `не подходит: ${l.reason}` : '✓ подходит'}
              {l.sent && ' · присылал'}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <NoteChips bike={l.bike} />
              <NoteButton bike={l.bike} lot={l.key} title={`${l.model} ${l.year ?? ''}`} />
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

/** Unsold with a bid within the limit: worth haggling over, and watched for a relist. */
export function WatchedList({ items }: { items: Watched[] }) {
  if (!items.length)
    return <Empty>За последние два месяца не было непроданных Tracer со ставкой в пределах лимита.</Empty>
  return (
    <ul className="flex flex-col divide-y rounded-xl border bg-card">
      {items.map((w) => (
        <li key={w.key} className="flex gap-3 p-3">
          <Photo src={w.photo} alt={w.model} className="size-16 shrink-0 rounded-md" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="font-medium">
              <Ext href={w.url}>
                {w.model} · {w.year ?? '?'}
              </Ext>
            </span>
            <p className="tabular text-sm">
              {joinParts(w.date && shortDate(w.date), w.auction)}: ставка дошла до <b>{yen(w.bid)}</b>, продавец не отдал
            </p>
            <p className="tabular text-xs text-muted-foreground">{joinParts(`оценка ${grade(w.rank)}`, km(w.mileage))}</p>
            <p className="text-xs">
              {w.relisted ? (
                <span className="font-medium text-ok">
                  🔁 снова на торгах {shortDate(w.relisted.date)}, старт {yenShort(w.relisted.start)} —{' '}
                  <Ext href={w.relisted.url}>открыть</Ext>
                </span>
              ) : (
                <span className="text-muted-foreground">Жду перевыставления: бот узнает его по раме.</span>
              )}
            </p>
            <NoteChips bike={w.bike} />
          </div>
        </li>
      ))}
    </ul>
  )
}

const KIND: Record<string, string> = { alert: 'подходящий лот', relist: 'перевыставлен', unsold: 'не продан в лимит' }

/** What the bot has sent to Telegram, with the auction outcome. */
export function HistoryList({ items }: { items: HistoryItem[] }) {
  const now = useNow()
  if (!items.length) return <Empty>Бот ещё ничего не присылал.</Empty>
  return (
    <ul className="flex flex-col divide-y rounded-xl border bg-card">
      {items.map((h) => {
        let outcome: React.ReactNode
        if (h.result?.sold) outcome = <span className="font-medium">✅ продан за {yen(h.result.price)}</span>
        else if (h.result) outcome = <span className="font-medium text-warn">❌ не продан, ставка {yen(h.result.price)}</span>
        else if (h.done) outcome = <span className="text-muted-foreground">итог не появился</span>
        else if (h.date_ts && h.date_ts > now) outcome = <span className="text-muted-foreground">торги впереди</span>
        else outcome = <span className="text-muted-foreground">жду итог торгов</span>
        return (
          <li key={h.key} className="flex flex-col gap-1 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-medium">
                <Ext href={h.url}>{h.title}</Ext>
              </span>
              <span className="text-xs text-muted-foreground">
                {joinParts(KIND[h.kind] ?? 'лот', h.sent_at ? dateTime(h.sent_at) : null)}
              </span>
            </div>
            <p className="tabular text-sm">{outcome}</p>
            {h.bike && <NoteChips bike={h.bike} />}
          </li>
        )
      })}
    </ul>
  )
}
