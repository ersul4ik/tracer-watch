import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Header } from '@/components/Header'
import { Empty, HistoryList, OnSale, WatchedList } from '@/components/Lists'
import { LotCard } from '@/components/LotCard'
import { Settings } from '@/components/Settings'
import { useBoard } from '@/hooks/useBoard'
import { AppContext } from '@/lib/context'
import { HIDING_LABELS, isHidden } from '@/lib/notes'

// The archive pulls in the charting library: load it only when the tab is opened
const Archive = lazy(() => import('@/components/Archive').then((m) => ({ default: m.Archive })))

const TABS = ['match', 'sale', 'unsold', 'sent', 'archive'] as const
type Tab = (typeof TABS)[number]

// A tab can be opened by link: …/tracer-watch/#archive
function initialTab(): Tab {
  const h = window.location.hash.slice(1)
  return (TABS as readonly string[]).includes(h) ? (h as Tab) : 'match'
}

export default function App() {
  const { board, error, loading, refresh, pending, sendNote, dropPending } = useBoard()
  const [tab, setTab] = useState<Tab>(initialTab)
  const [settings, setSettings] = useState(false)
  const [hideMarked, setHideMarked] = useState(false)
  const tabsRef = useRef<HTMLDivElement>(null)

  // A link or the back button changes the hash: follow it
  useEffect(() => {
    const onHash = () => setTab(initialTab())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // On a phone not every tab fits: keep the active one in view
  useEffect(() => {
    tabsRef.current?.querySelector('[data-state="active"]')?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [tab, board])

  const allMatching = useMemo(() => (board?.lots ?? []).filter((l) => !l.reason), [board])
  const matching = allMatching.filter((l) => !hideMarked || !isHidden(board, l.bike))
  const scanEvery = board ? (board.scan_every_min >= 60 ? `${Math.round(board.scan_every_min / 60)} ч` : `${board.scan_every_min} мин`) : ''

  const ctx = { board, pending, sendNote, dropPending, openSettings: () => setSettings(true) }

  return (
    <AppContext.Provider value={ctx}>
      <TooltipProvider>
        <div className="mx-auto flex max-w-5xl flex-col gap-5 px-[max(16px,env(safe-area-inset-left))] py-6">
          <Header board={board} loading={loading} onRefresh={refresh} onSettings={() => setSettings(true)} />

          {error && (
            <p className="rounded-lg bg-bad-soft p-4 text-sm text-bad">
              {board ? `Не удалось обновить данные: ${error}. Показываю последние загруженные.` : `${error}. Попробуй обновить страницу.`}
            </p>
          )}

          {!board && !error && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Skeleton className="h-96" />
              <Skeleton className="h-96" />
            </div>
          )}

          {board && (
            <Tabs
              value={tab}
              onValueChange={(v) => {
                setTab(v as Tab)
                history.replaceState(null, '', `#${v}`)
              }}
              className="gap-4"
            >
              <div ref={tabsRef} className="-mx-4 overflow-x-auto px-4">
                <TabsList>
                  <TabsTrigger value="match">Подходят · {matching.length}</TabsTrigger>
                  <TabsTrigger value="sale">В продаже · {board.counts.for_sale}</TabsTrigger>
                  <TabsTrigger value="unsold">Не продали · {board.watched.length}</TabsTrigger>
                  <TabsTrigger value="sent">Присылал · {board.history.length}</TabsTrigger>
                  <TabsTrigger value="archive">Архив</TabsTrigger>
                </TabsList>
              </div>

              {(tab === 'match' || tab === 'sale') && (
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Switch id="hide-marked" checked={hideMarked} onCheckedChange={setHideMarked} />
                  скрыть с метками {HIDING_LABELS}
                </label>
              )}

              <TabsContent value="match">
                {matching.length ? (
                  <div className="grid items-start gap-4 sm:grid-cols-2">
                    {matching.map((l) => (
                      <LotCard key={l.key} lot={l} />
                    ))}
                  </div>
                ) : allMatching.length ? (
                  <Empty>
                    Все подходящие лоты скрыты: у них метки {HIDING_LABELS}. Выключи фильтр, чтобы их увидеть.
                  </Empty>
                ) : (
                  <Empty>
                    Сейчас подходящих лотов нет. Бот проверяет сайты каждые {scanEvery} и напишет в Telegram, как только
                    появится.
                  </Empty>
                )}
              </TabsContent>
              <TabsContent value="sale">
                <OnSale lots={board.lots} hideMarked={hideMarked} />
              </TabsContent>
              <TabsContent value="unsold">
                <WatchedList items={board.watched} />
              </TabsContent>
              <TabsContent value="sent">
                <HistoryList items={board.history} />
              </TabsContent>
              <TabsContent value="archive">
                <Suspense fallback={<Skeleton className="h-72" />}>
                  <Archive rows={board.archive} />
                </Suspense>
              </TabsContent>
            </Tabs>
          )}

          <footer className="pb-4 text-xs text-muted-foreground">
            {board && <>Всего бот видел {board.counts.seen_total} лотов Tracer. </>}
            Данные: motoauction.online и projapan.ru.
          </footer>
        </div>
        <Settings open={settings} onOpenChange={setSettings} />
      </TooltipProvider>
    </AppContext.Provider>
  )
}
