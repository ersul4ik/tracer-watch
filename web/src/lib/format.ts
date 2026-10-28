const nf = new Intl.NumberFormat('ru-RU')

export const yen = (v: number | null | undefined) => (v ? `${nf.format(v)} ¥` : '—')

// 750000 -> "750к", 1285000 -> "1,29 млн": compact enough for chips and chart axes
export const yenShort = (v: number | null | undefined) => {
  if (!v) return '—'
  if (v >= 1_000_000) return `${(v / 1_000_000).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} млн`
  return `${Math.round(v / 1000)}к`
}

export const km = (v: number | null | undefined) => (v || v === 0 ? `${nf.format(v)} км` : '—')

export const grade = (v: number | null | undefined) => (v ? String(v).replace(/\.0$/, '') : '—')

export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}

/** Whole days from today (viewer's clock) to an ISO date; days in board.json go stale between scans. */
export function daysUntil(iso: string | null, fallback = 0) {
  if (!iso) return fallback
  const [y, m, d] = iso.split('-').map(Number)
  const today = new Date()
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((Date.UTC(y, m - 1, d) - start) / 86_400_000)
}

export function daysLeft(days: number) {
  if (days < 0) return 'торги прошли'
  if (days === 0) return 'торги сегодня'
  if (days === 1) return 'торги завтра'
  return `через ${days} ${plural(days, 'день', 'дня', 'дней')}`
}

export function ago(ts: number, now = Date.now() / 1000) {
  const min = Math.max(0, Math.round((now - ts) / 60))
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} ч ${min % 60} мин назад`
  const d = Math.floor(h / 24)
  return `${d} ${plural(d, 'день', 'дня', 'дней')} назад`
}

export const dateTime = (ts: number) =>
  new Date(ts * 1000).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

export const shortDate = (d: string | null | undefined) => (d ? d.slice(0, 5) : '—')

// Model group from bot/pricing.py stats_model -> a name a person reads
export function groupName(group: string) {
  if (group === 'MT-09TRACER') return 'Tracer 900'
  if (group === 'MT-09TRACERGT') return 'Tracer 900 GT'
  if (group.startsWith('TRACER9GT+')) return 'Tracer 9 GT+'
  if (group.startsWith('TRACER9GT')) return 'Tracer 9 GT'
  return group
}
