import { useMemo, useState } from 'react'
import { CartesianGrid, ReferenceLine, Scatter, ScatterChart, XAxis, YAxis } from 'recharts'
import { ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ChartContainer, ChartTooltip, type ChartConfig } from '@/components/ui/chart'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Empty } from '@/components/Lists'
import { NoteChips } from '@/components/Notes'
import { useApp } from '@/lib/context'
import { grade, groupName, joinParts, km, sales, shortDate, yen, yenShort } from '@/lib/format'
import type { ArchiveRow } from '@/lib/types'
import { cn } from '@/lib/utils'

const chartConfig = {
  sold: { label: 'Продан', color: 'var(--chart-1)' },
  unsold: { label: 'Не продан (ставка)', color: 'var(--chart-3)' },
  curve: { label: 'Типичная цена', color: 'var(--chart-5)' },
} satisfies ChartConfig

// Axis labels must fit in ~50px: 2,2М / 750к
const axisYen = (v: number) =>
  v >= 1_000_000 ? `${(v / 1_000_000).toLocaleString('ru-RU', { maximumFractionDigits: 2 })}М` : `${Math.round(v / 1000)}к`

interface Point {
  x: number
  y: number
  row: ArchiveRow
}

function PointTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point | { x: number; y: number } }[] }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  if (!('row' in p)) return null
  const r = p.row
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="font-medium">
        {r.model} · {r.year}
      </div>
      <div className="tabular text-muted-foreground">
        оценка {grade(r.rank)} · {km(r.mileage)} · {shortDate(r.date)}
      </div>
      <div className="tabular mt-1">
        {r.sold ? 'продан за ' : 'не продан, ставка '}
        <b>{yen(r.price)}</b>
      </div>
    </div>
  )
}

/** Past auctions: who sold for how much, and how price falls with mileage. */
export function Archive({ rows }: { rows: ArchiveRow[] }) {
  const { board } = useApp()
  const [group, setGroup] = useState('all')
  const [fromYear, setFromYear] = useState(() => {
    // the bot's minimum year, if the archive has sales from it; otherwise any year
    const y = board?.limits.min_year
    return y && rows.some((r) => (r.year ?? 0) >= y) ? String(y) : 'all'
  })
  const [goodOnly, setGoodOnly] = useState(true)
  const [withUnsold, setWithUnsold] = useState(false)
  const [limit, setLimit] = useState(40)

  const groups = useMemo(() => [...new Set(rows.map((r) => r.group))].sort(), [rows])
  const years = useMemo(() => [...new Set(rows.map((r) => r.year).filter(Boolean) as number[])].sort(), [rows])

  const filtered = useMemo(
    () =>
      rows.filter(
        (r) =>
          (group === 'all' || r.group === group) &&
          (fromYear === 'all' || (r.year ?? 0) >= Number(fromYear)) &&
          (!goodOnly || (r.rank ?? 0) >= (board?.limits.min_rank ?? 4)) &&
          (withUnsold || r.sold),
      ),
    [rows, group, fromYear, goodOnly, withUnsold, board],
  )

  const sold = filtered.filter((r) => r.sold && r.mileage != null)
  const unsold = filtered.filter((r) => !r.sold && r.mileage != null)
  const toPoint = (r: ArchiveRow): Point => ({ x: Math.round((r.mileage ?? 0) / 1000), y: r.price, row: r })

  // The typical-price curve uses the same rate the bot fits: price ~ P0 * exp(-k * km)
  const curve = useMemo(() => {
    const k = board?.per_km
    if (!k || sold.length < 3) return []
    const p0s = sold.map((r) => r.price * Math.exp((k * (r.mileage ?? 0)) / 1000)).sort((a, b) => a - b)
    const p0 = p0s[Math.floor(p0s.length / 2)]
    const maxKm = Math.max(...sold.map((r) => (r.mileage ?? 0) / 1000), 20)
    return Array.from({ length: 21 }, (_, i) => {
      const x = (maxKm * i) / 20
      return { x: Math.round(x), y: Math.round(p0 * Math.exp(-k * x)) }
    })
  }, [sold, board])

  const ourLimit = board?.limits.limit
  const soldAll = filtered.filter((r) => r.sold)
  const inLimit = soldAll.filter((r) => ourLimit && r.price <= ourLimit).length
  const noKm = soldAll.length - sold.length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select value={group} onValueChange={setGroup}>
          <SelectTrigger className="w-40" aria-label="Модель">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все модели</SelectItem>
            {groups.map((g) => (
              <SelectItem key={g} value={g}>
                {groupName(g)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={fromYear} onValueChange={setFromYear}>
          <SelectTrigger className="w-32" aria-label="Год от">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Любой год</SelectItem>
            {years.map((y) => (
              <SelectItem key={y} value={String(y)}>
                с {y}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <Switch id="archive-good" checked={goodOnly} onCheckedChange={setGoodOnly} />
          оценка от {board?.limits.min_rank ?? 4}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Switch id="archive-unsold" checked={withUnsold} onCheckedChange={setWithUnsold} />
          и непроданные
        </label>
      </div>

      <p className="text-sm text-muted-foreground">
        {sales(soldAll.length)} за год
        {ourLimit ? `, из них в наш лимит ${yenShort(ourLimit)}: ${inLimit}` : ''}
        {noKm ? ` (на графике без ${noKm} с неизвестным пробегом)` : ''}. Пунктир — типичная цена с учётом пробега, красная
        линия — наш лимит.
      </p>

      {sold.length + unsold.length > 0 ? (
        <ChartContainer config={chartConfig} className="aspect-auto h-72 w-full">
          <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="x"
              name="Пробег"
              tickLine={false}
              axisLine={false}
              domain={[0, 'dataMax']}
              tickFormatter={(v) => `${v}к км`}
            />
            <YAxis
              type="number"
              dataKey="y"
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={axisYen}
              domain={['auto', 'auto']}
            />
            {/* ScatterChart gives a per-point tooltip; a shared, axis-wide one picked up the curve or a neighbour */}
            <ChartTooltip content={<PointTooltip />} cursor={{ strokeDasharray: '3 3' }} />
            {ourLimit && (
              <ReferenceLine
                y={ourLimit}
                stroke="var(--bad)"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                label={{ value: 'лимит', position: 'insideBottomLeft', fill: 'var(--bad)', fontSize: 11 }}
              />
            )}
            {curve.length > 0 && (
              <Scatter
                data={curve}
                line={{ stroke: 'var(--color-curve)', strokeDasharray: '6 4', strokeWidth: 2 }}
                lineType="joint"
                shape={() => <g />}
                legendType="none"
                isAnimationActive={false}
              />
            )}
            <Scatter data={sold.map(toPoint)} fill="var(--color-sold)" isAnimationActive={false} />
            {withUnsold && <Scatter data={unsold.map(toPoint)} fill="var(--color-unsold)" shape="diamond" isAnimationActive={false} />}
          </ScatterChart>
        </ChartContainer>
      ) : (
        <Empty>Под эти фильтры продаж нет.</Empty>
      )}

      {filtered.length > 0 && (
      <ul className="flex flex-col divide-y rounded-xl border bg-card">
        {filtered.slice(0, limit).map((r) => {
          const delta = r.sold && r.estimate ? Math.round(((r.price - r.estimate) / r.estimate) * 100) : null
          return (
            <li key={r.key} className="flex flex-col gap-0.5 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <a href={r.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium hover:underline">
                  {r.model} · {r.year}
                  <ExternalLink className="size-3 opacity-60" />
                </a>
                <span className="tabular text-sm">
                  {r.sold ? '' : 'ставка '}
                  <b className={cn(ourLimit && r.sold && r.price <= ourLimit && 'text-ok')}>{yen(r.price)}</b>
                </span>
              </div>
              <div className="tabular flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground">
                <span>{joinParts(shortDate(r.date), r.auction, `оценка ${grade(r.rank)}`, km(r.mileage))}</span>
                <span>
                  {r.sold ? (
                    <>
                      {r.estimate && <>обычно ~{yenShort(r.estimate)} </>}
                      {delta !== null && (
                        <span className={cn('font-medium', delta <= -5 ? 'text-ok' : delta >= 5 ? 'text-warn' : '')}>
                          ({delta > 0 ? '+' : ''}
                          {delta}%)
                        </span>
                      )}
                    </>
                  ) : (
                    'не продан'
                  )}
                </span>
              </div>
              <NoteChips bike={r.bike} className="mt-1" />
            </li>
          )
        })}
      </ul>
      )}
      {filtered.length > limit && (
        <Button variant="outline" onClick={() => setLimit(limit + 60)}>
          Показать ещё ({filtered.length - limit})
        </Button>
      )}
    </div>
  )
}
