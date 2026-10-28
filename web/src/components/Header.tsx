import { RefreshCw, Settings as SettingsIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useNow } from '@/hooks/useNow'
import { ago, dateTime, yenShort } from '@/lib/format'
import type { Board } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Title, when the bot last checked the sites (red when it is overdue), limits and counts. */
export function Header({ board, loading, onRefresh, onSettings }: {
  board: Board | null
  loading: boolean
  onRefresh: () => void
  onSettings: () => void
}) {
  const now = useNow()
  // One missed check is fine; a gap of a scan interval plus an hour means the bot is stuck
  const stale = board ? now - board.updated_at > (board.scan_every_min + 60) * 60 : false
  return (
    <header className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tracer Watch</h1>
          <p className="text-sm text-muted-foreground">Yamaha Tracer на японских аукционах: BDS, JBA, AUCNET</p>
        </div>
        <div className="flex gap-1.5">
          <Button variant="outline" size="icon" onClick={onRefresh} aria-label="Обновить">
            <RefreshCw className={cn(loading && 'animate-spin')} />
          </Button>
          <Button variant="outline" size="icon" onClick={onSettings} aria-label="Настройки">
            <SettingsIcon />
          </Button>
        </div>
      </div>
      {board && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
          <span className={cn('tabular', stale ? 'font-medium text-bad' : 'text-muted-foreground')}>
            {stale ? '⚠️ бот давно не проверял: ' : 'обновлено '}
            {dateTime(board.updated_at)} · {ago(board.updated_at, now)}
          </span>
          <span className="tabular text-muted-foreground">
            лимит {yenShort(board.limits.limit)}, при оценке {board.limits.top_rank}+ — {yenShort(board.limits.top_limit)}
          </span>
          {!board.projapan_ok && <span className="text-warn">projapan не ответил, только motoauction</span>}
        </div>
      )}
    </header>
  )
}
