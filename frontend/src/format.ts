// Display formatting helpers. Numbers render with fixed precision so columns
// align; nulls render as an em dash rather than "null".

export const DASH = '—'

export function money(v: number | null | undefined, dp = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return v.toFixed(dp)
}

export function pct(v: number | null | undefined, dp = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return (v * 100).toFixed(dp) + '%'
}

export function int(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return Math.round(v).toLocaleString()
}

export function greek(v: number | null | undefined, dp = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return v.toFixed(dp)
}

export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return ''
  return v > 0 ? 'pos' : v < 0 ? 'neg' : ''
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
