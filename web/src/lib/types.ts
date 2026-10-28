// Shape of board.json, written by bot/export.py

export interface Estimate {
  median: number
  n: number
  lo: number
  hi: number
  scope: string
}

export interface InspectionLine {
  text: string
  serious: boolean
  kind: 'comment' | 'note' | 'info'
}

export interface Lot {
  key: string
  bike: string
  site: 'motoauction' | 'projapan'
  model: string
  group: string
  year: number | null
  rank: number | null
  mileage: number | null
  start: number | null
  date: string | null
  date_iso: string | null
  days: number
  auction: string | null
  lot_no: string | null
  frame: string | null
  color: string | null
  photo: string | null
  links: { site: string; url: string }[]
  reason: string | null
  sent: boolean
  limit: number
  estimate: Estimate | null
  site_avg: number | null
  relist_of: { key: string; date: string; auction: string; bid: number } | null
  flags: { near: boolean; top: boolean; pricey: boolean; no_rank: boolean }
  inspection: InspectionLine[]
  serious: boolean
}

export interface Watched {
  key: string
  bike: string
  model: string
  year: number | null
  rank: number | null
  mileage: number | null
  bid: number
  date: string
  date_iso: string | null
  auction: string
  url: string
  photo: string | null
  relisted: { key: string; url: string; date: string; start: number } | null
}

export interface HistoryItem {
  key: string
  bike: string | null
  title: string
  url: string | null
  sent_at: number
  date_ts: number | null
  done: boolean
  kind: 'alert' | 'relist' | 'unsold'
  result: { sold: boolean; price: number } | null
}

export interface ArchiveRow {
  key: string
  bike: string
  model: string
  group: string
  year: number | null
  rank: number | null
  mileage: number | null
  price: number
  sold: boolean
  site_avg: number | null
  estimate: number | null
  date: string
  date_iso: string | null
  auction: string
  url: string
  photo: string | null
}

export interface Note {
  id: number
  tag: string
  text: string
  source: 'web' | 'telegram' | 'cli'
  created_at: number
  lot_key: string | null
}

export interface Board {
  version: number
  updated_at: number
  updated_iso: string
  scan_every_min: number
  limits: {
    limit: number
    top_limit: number
    top_rank: number
    min_year: number
    min_rank: number
    expect_ratio: number
    near_ratio: number
  }
  per_km: number | null
  projapan_ok: boolean
  counts: { for_sale: number; matching: number; sent: number; archive: number; seen_total: number }
  lots: Lot[]
  watched: Watched[]
  history: HistoryItem[]
  archive: ArchiveRow[]
  notes: Record<string, Note[]>
  notes_at: number
}
