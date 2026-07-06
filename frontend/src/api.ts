// Typed client for the backend API. All requests go through the Vite proxy at
// /api, so the browser stays same-origin and never sees the Alpaca keys.

export interface Greeks {
  delta: number | null
  gamma: number | null
  vega: number | null
  theta: number | null
  rho: number | null
}

export interface Contract {
  symbol: string
  type: 'call' | 'put'
  strike: number
  expiration: string
  bid: number | null
  ask: number | null
  mid: number | null
  last: number | null
  volume: number | null
  open_interest: number | null
  iv: number | null
  iv_source: string | null
  greeks: Greeks
  in_the_money: boolean | null
}

export interface IvRank {
  value: number
  rank: number
  percentile: number
  window: number
  proxy: string
}

export interface MarketStatus {
  is_open: boolean | null
  timestamp?: string
  next_open?: string
  next_close?: string
  source: string
}

export interface ChainResponse {
  ticker: string
  spot: number | null
  as_of: string
  rate: { source: string; as_of: string | null; points: Record<string, number> }
  dividend: { value: number; source: string }
  iv_source: string
  market: MarketStatus
  expirations: string[]
  iv_rank: IvRank | null
  contracts: Contract[]
}

export interface Assumptions {
  ticker: string
  rate: {
    source: string
    as_of: string | null
    points: Record<string, number>
    sample: Record<string, number>
  }
  dividend: { value: number; source: string }
}

export interface SurfacePoint { strike: number; expiration: string; tenor: number; iv: number }
export interface SurfaceResponse {
  ticker: string; spot: number | null; as_of: string
  expirations: string[]; points: SurfacePoint[]
}

export interface SmilePoint {
  strike: number; iv: number; type: 'call' | 'put'; in_the_money: boolean | null
}
export interface SmileLeg { strike: number; iv: number; delta: number }
export interface SmileResponse {
  ticker: string; expiration: string; spot: number | null; forward: number | null
  r: number; q: number; t: number; as_of: string
  atm_iv: number | null; rr_25: number | null; bf_25: number | null
  call_25: SmileLeg | null; put_25: SmileLeg | null
  points: SmilePoint[]
}

export interface ConeBand {
  min: number; p25: number; median: number; p75: number; max: number
  current: number; samples: number
}
export interface RealizedVsImplied {
  ticker: string
  spot: number | null
  atm_iv: number | null
  atm_expiration: string
  realized_vol: Record<string, number | null>       // primary (Garman-Klass)
  realized_vol_gk: Record<string, number | null>
  realized_vol_cc: Record<string, number | null>
  iv_rank: IvRank | null
  vrp: { spread: number; ratio: number; basis: string } | null
  divergence: {
    window: number; gk: number; cc: number; rel_diff: number
    flag: boolean; gk_below_cc: boolean
  } | null
  cone: Record<string, ConeBand | null>
}

export interface ExpirationsResponse { ticker: string; expirations: string[] }

async function get<T>(path: string, params: Record<string, string | number | undefined>): Promise<T> {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const res = await fetch(`/api/${path}?${q.toString()}`)
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* keep */ }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  chain: (ticker: string, ivSource: string, numExpirations: number) =>
    get<ChainResponse>('chain', { ticker, iv_source: ivSource, num_expirations: numExpirations }),
  assumptions: (ticker: string) => get<Assumptions>('assumptions', { ticker }),
  marketStatus: () => get<MarketStatus>('market-status', {}),
  expirations: (ticker: string) => get<ExpirationsResponse>('expirations', { ticker }),
  surface: (ticker: string, ivSource: string, maxExpirations = 8) =>
    get<SurfaceResponse>('analysis/surface', { ticker, iv_source: ivSource, max_expirations: maxExpirations }),
  smile: (ticker: string, expiration: string, ivSource: string) =>
    get<SmileResponse>('analysis/smile', { ticker, expiration, iv_source: ivSource }),
  realizedVsImplied: (ticker: string) =>
    get<RealizedVsImplied>('analysis/realized-vs-implied', { ticker }),
}
