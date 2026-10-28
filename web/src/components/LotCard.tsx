import { ChevronDown, ExternalLink, ImageOff } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { NoteButton, NoteChips } from '@/components/Notes'
import { daysLeft, daysUntil, grade, joinParts, km, sales, yen, yenShort } from '@/lib/format'
import type { Lot } from '@/lib/types'
import { cn } from '@/lib/utils'

export function Photo({ src, alt, className }: { src: string | null; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed)
    return (
      <div className={cn('flex items-center justify-center bg-muted text-muted-foreground', className)}>
        <ImageOff className="size-6" />
      </div>
    )
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={cn('bg-muted object-cover', className)}
    />
  )
}

function Flag({ tone, children }: { tone: 'ok' | 'warn' | 'bad' | 'info'; children: React.ReactNode }) {
  const tones = {
    ok: 'bg-ok-soft text-ok',
    warn: 'bg-warn-soft text-warn',
    bad: 'bg-bad-soft text-bad',
    info: 'bg-accent text-accent-foreground',
  }
  return <span className={cn('rounded-md px-2 py-0.5 text-xs font-medium', tones[tone])}>{children}</span>
}

function Row({ label, children, strong }: { label: string; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn('tabular text-right', strong && 'font-semibold')}>{children}</dd>
    </div>
  )
}

/** One lot on sale that matches the criteria: photo, prices, flags, inspection sheet, notes. */
export function LotCard({ lot }: { lot: Lot }) {
  const title = `${lot.model} · ${lot.year ?? 'год ?'}`
  const serious = lot.inspection.filter((x) => x.serious)
  const days = daysUntil(lot.date_iso)
  const urgent = days !== null && days <= 1
  return (
    <Card className="overflow-hidden pt-0">
      <div className="relative">
        <Photo src={lot.photo} alt={title} className="aspect-[4/3] w-full" />
        <div className="absolute inset-x-2 top-2 flex flex-wrap gap-1.5">
          <Badge className={cn(urgent ? 'bg-bad-strong text-white' : 'bg-background/90 text-foreground backdrop-blur')}>
            {joinParts(daysLeft(days), lot.date?.slice(0, 5))}
          </Badge>
          {lot.sent && <Badge className="bg-background/90 text-foreground backdrop-blur">присылал в Telegram</Badge>}
        </div>
      </div>
      <CardContent className="flex flex-col gap-3">
        <div>
          <h3 className="text-lg leading-tight font-semibold text-balance [overflow-wrap:anywhere]">{title}</h3>
          <p className="tabular mt-1 text-sm text-muted-foreground">
            оценка <span className="font-semibold text-foreground">{grade(lot.rank)}</span> ·{' '}
            {joinParts(km(lot.mileage), lot.auction, lot.lot_no && `лот ${lot.lot_no}`, lot.color)}
          </p>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {lot.relist_of && (
            <Flag tone="info">
              🔁 перевыставлен{lot.relist_of.bid ? `: ${lot.relist_of.date?.slice(0, 5) ?? ''} ставка дошла до ${yenShort(lot.relist_of.bid)}` : ''}
            </Flag>
          )}
          {lot.flags.top && <Flag tone="ok">🔥 топ-оценка</Flag>}
          {lot.flags.near && <Flag tone="warn">🟡 старт уже выше лимита</Flag>}
          {lot.flags.pricey && <Flag tone="warn">⚠️ обычно уходят дороже лимита</Flag>}
          {lot.flags.no_rank && <Flag tone="warn">⏳ оценки пока нет</Flag>}
          {lot.inspection.length > 0 &&
            (lot.serious ? <Flag tone="bad">🔧 серьёзные замечания: {serious.length}</Flag> : <Flag tone="ok">✅ без серьёзных замечаний</Flag>)}
        </div>

        <dl className="flex flex-col gap-1 text-sm">
          <Row label="Старт">{lot.start ? yen(lot.start) : 'пока неизвестен'}</Row>
          <Row label="Обычно уходят за">
            {lot.estimate ? (
              <>
                ~{yen(lot.estimate.median)}
                <span className="block text-xs text-muted-foreground">
                  {yenShort(lot.estimate.lo)}–{yenShort(lot.estimate.hi)}, {sales(lot.estimate.n)}
                </span>
              </>
            ) : lot.site_avg ? (
              <>~{yen(lot.site_avg)} (средняя с сайта)</>
            ) : (
              '—'
            )}
          </Row>
          <Row label="Наш лимит" strong>
            {yen(lot.limit)}
          </Row>
        </dl>
        {lot.estimate && <p className="text-xs text-muted-foreground">{lot.estimate.scope}</p>}

        {lot.inspection.length > 0 && (
          <Collapsible defaultOpen={lot.serious}>
            <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-md py-1 text-sm font-medium">
              Лист осмотра
              <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className="mt-1 flex flex-col gap-1.5 text-sm">
                {lot.inspection.map((x, i) => (
                  <li
                    key={i}
                    className={cn(
                      'rounded-md px-2.5 py-1.5 [overflow-wrap:anywhere]',
                      x.serious ? 'bg-bad-soft' : x.kind === 'comment' ? 'bg-accent' : 'bg-muted',
                    )}
                  >
                    {x.serious && '❗ '}
                    {x.kind === 'comment' && '💬 '}
                    {x.text}
                  </li>
                ))}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        )}

        <NoteChips bike={lot.bike} />
      </CardContent>
      <CardFooter className="mt-auto flex flex-wrap gap-2">
        {lot.links.map((l) => (
          <Button key={l.url} asChild variant="secondary" size="sm">
            <a href={l.url} target="_blank" rel="noreferrer">
              {l.site}
              <ExternalLink data-icon="inline-end" />
            </a>
          </Button>
        ))}
        <NoteButton bike={lot.bike} lot={lot.key} title={title} />
      </CardFooter>
    </Card>
  )
}
