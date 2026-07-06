import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api } from '../api'
import { pct, money } from '../format'
import { baseLayout, plotColors, ivColorscale, cssVar, plotConfig } from '../plotTheme'

type Tab = 'surface' | 'smile' | 'realized'

function lerp(pts: { strike: number; iv: number }[], x: number): number | null {
  if (pts.length === 0 || x < pts[0].strike || x > pts[pts.length - 1].strike) return null
  for (let i = 1; i < pts.length; i++) {
    if (x <= pts[i].strike) {
      const a = pts[i - 1], b = pts[i]
      const t = (x - a.strike) / (b.strike - a.strike || 1)
      return a.iv + t * (b.iv - a.iv)
    }
  }
  return pts[pts.length - 1].iv
}

// 3-point moving average along a row (over defined values).
function smoothRow(row: (number | null)[]): (number | null)[] {
  return row.map((v, i) => {
    if (v == null) return null
    const w = [row[i - 1], v, row[i + 1]].filter((x): x is number => x != null)
    return w.reduce((s, x) => s + x, 0) / w.length
  })
}

// Clean one expiration's smile: drop spikes that deviate sharply from neighbours,
// then a rolling median to tame stale-quote runs. Shared by the smile and surface.
function cleanSmile(sorted: { strike: number; iv: number }[]): { strike: number; iv: number }[] {
  const deSpiked = sorted.filter((p, i) => {
    if (i === 0 || i === sorted.length - 1) return true
    const nb = (sorted[i - 1].iv + sorted[i + 1].iv) / 2
    return Math.abs(p.iv - nb) < nb * 0.5
  })
  const w = 2
  return deSpiked.map((p, i) => {
    const win = deSpiked.slice(Math.max(0, i - w), i + w + 1).map((x) => x.iv).sort((a, b) => a - b)
    return { strike: p.strike, iv: win[Math.floor(win.length / 2)] }
  })
}

// Smooth a grid across rows (tenor) at each column, so the surface is not ridged
// between adjacent expirations.
function smoothCols(z: (number | null)[][]): (number | null)[][] {
  return z.map((row, i) =>
    row.map((v, j) => {
      if (v == null) return null
      const w = [z[i - 1]?.[j], v, z[i + 1]?.[j]].filter((x): x is number => x != null)
      return w.reduce((s, x) => s + x, 0) / w.length
    }),
  )
}

function volPts(x: number | null | undefined): string {
  if (x === null || x === undefined) return '—'
  const p = x * 100
  return (p >= 0 ? '+' : '') + p.toFixed(1) + ' pts'
}

function interpretSmile(rr: number | null, bf: number | null): string {
  if (rr === null || rr === undefined) return 'Not enough delta coverage to read the skew for this expiration.'
  const rrp = rr * 100
  const bfp = (bf ?? 0) * 100
  let s: string
  if (rrp < -4) s = 'Pronounced put skew. Out-of-the-money puts carry much richer implied vol than calls, so the market is pricing downside protection heavily. This is the normal state for an equity index.'
  else if (rrp < -1.5) s = 'Downward skew. Downside is priced richer than upside, the typical shape for an equity index.'
  else if (rrp > 4) s = 'Call skew. Upside is priced richer than downside, unusual for an index and more typical of a squeeze or a single name.'
  else s = 'Roughly symmetric skew. The market is pricing moves in either direction similarly, common around a binary event such as earnings.'
  if (bfp > 3) s += ' The wings sit well above the at-the-money level, a sign of demand for large-move protection on both sides.'
  return s
}

export default function AnalysisPage() {
  const { ticker, ivSource, theme } = useStore()
  const [tab, setTab] = useState<Tab>('surface')

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title"><span className="tk">{ticker}</span> Volatility</div>
      </div>
      <div className="tabs">
        <button className={tab === 'surface' ? 'active' : ''} onClick={() => setTab('surface')}>Volatility Surface</button>
        <button className={tab === 'smile' ? 'active' : ''} onClick={() => setTab('smile')}>Volatility Smile</button>
        <button className={tab === 'realized' ? 'active' : ''} onClick={() => setTab('realized')}>Realized vs Implied</button>
      </div>
      {tab === 'surface' && <SurfaceTab ticker={ticker} ivSource={ivSource} themeKey={theme} />}
      {tab === 'smile' && <SmileTab ticker={ticker} ivSource={ivSource} themeKey={theme} />}
      {tab === 'realized' && <RealizedTab ticker={ticker} themeKey={theme} />}
    </div>
  )
}

function Loading({ label }: { label: string }) {
  return <div className="msg"><span className="spin" />{label}</div>
}
function Failed({ error }: { error: unknown }) {
  return <div className="msg err">Failed to load: {(error as Error).message}</div>
}

function SurfaceTab({ ticker, ivSource, themeKey }: { ticker: string; ivSource: string; themeKey: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['surface', ticker, ivSource],
    queryFn: () => api.surface(ticker, ivSource, 12),
  })
  const c = plotColors()

  const grid = useMemo(() => {
    if (!data) return null
    const spot = data.spot ?? 0
    const byTenor = new Map<number, { strike: number; iv: number }[]>()
    for (const p of data.points) {
      if (!(p.iv > 0 && p.iv <= 0.8)) continue
      if (p.tenor < 0.008) continue // skip 0-1 DTE rows; their IV is unreliable
      if (spot && (p.strike < spot * 0.8 || p.strike > spot * 1.2)) continue
      const arr = byTenor.get(p.tenor) ?? []
      arr.push({ strike: p.strike, iv: p.iv })
      byTenor.set(p.tenor, arr)
    }
    const tenors = [...byTenor.keys()].sort((a, b) => a - b)
    if (tenors.length < 2) return null
    const cleaned = new Map<number, { strike: number; iv: number }[]>()
    for (const t of tenors) cleaned.set(t, cleanSmile(byTenor.get(t)!.sort((a, b) => a.strike - b.strike)))
    const all = [...cleaned.values()].flat().map((p) => p.strike)
    const lo = Math.min(...all), hi = Math.max(...all)
    const N = 56
    const strikes = Array.from({ length: N }, (_, i) => lo + ((hi - lo) * i) / (N - 1))
    let z = tenors.map((t) => {
      const pts = cleaned.get(t)!
      return strikes.map((s) => { const v = lerp(pts, s); return v == null ? null : v * 100 })
    })
    for (let pass = 0; pass < 3; pass++) { z = z.map(smoothRow); z = smoothCols(z) }
    return { strikes, tenors, z }
  }, [data])

  if (isLoading) return <Loading label={`Loading surface for ${ticker}…`} />
  if (isError) return <Failed error={error} />
  if (!grid) return <div className="chart-card"><div className="msg">Not enough surface data.</div></div>

  const trace = {
    type: 'surface',
    x: grid.strikes, y: grid.tenors, z: grid.z,
    colorscale: ivColorscale(), showscale: true, opacity: 1,
    colorbar: { title: 'IV %', tickfont: { color: c.muted }, outlinecolor: c.grid, thickness: 10, len: 0.55 },
    lighting: { ambient: 0.85, diffuse: 0.45, specular: 0.05, roughness: 0.9, fresnel: 0.1 },
    lightposition: { x: 100, y: 200, z: 350 },
    hovertemplate: 'K %{x:.0f}<br>T %{y:.3f}y<br>IV %{z:.1f}%<extra></extra>',
  }
  const axis = {
    color: c.muted, gridcolor: c.grid, zerolinecolor: c.grid,
    showbackground: false, showspikes: false, tickfont: { color: c.muted },
  }
  const layout = {
    ...baseLayout(),
    height: 580,
    scene: {
      xaxis: { ...axis, title: { text: 'Strike' } },
      yaxis: { ...axis, title: { text: 'Tenor (yrs)' } },
      zaxis: { ...axis, title: { text: 'IV %' } },
      camera: { eye: { x: 1.45, y: -1.75, z: 0.42 } },
      aspectratio: { x: 1.7, y: 0.9, z: 0.55 },
    },
  }
  return (
    <div className="chart-card">
      <Plot key={themeKey} data={[trace]} layout={layout} config={plotConfig}
        style={{ width: '100%', height: 580 }} useResizeHandler />
      <div className="chart-note">
        IV interpolated across strike and expiration (near-money band), smoothed. Drag to rotate, scroll to zoom.
      </div>
    </div>
  )
}

function SmileTab({ ticker, ivSource, themeKey }: { ticker: string; ivSource: string; themeKey: string }) {
  const exps = useQuery({ queryKey: ['exps', ticker], queryFn: () => api.expirations(ticker) })
  const [exp, setExp] = useState<string | null>(null)
  useEffect(() => {
    if (exps.data && (!exp || !exps.data.expirations.includes(exp))) {
      // Default to the first expiration at least a week out; the nearest ones are
      // near-expiry and their skew metrics are undefined.
      const list = exps.data.expirations
      const soon = list.find((e) => (Date.parse(e) - Date.now()) / 86400000 >= 7)
      setExp(soon ?? list[0] ?? null)
    }
  }, [exps.data, exp])

  const smile = useQuery({
    queryKey: ['smile', ticker, exp, ivSource],
    queryFn: () => api.smile(ticker, exp!, ivSource),
    enabled: !!exp,
  })
  const c = plotColors()

  const pts = useMemo(() => {
    if (!smile.data) return [] as { strike: number; iv: number }[]
    const m = new Map<number, number>()
    for (const p of smile.data.points) {
      if (p.iv > 0.02 && p.iv <= 1.0 && !m.has(p.strike)) m.set(p.strike, p.iv)
    }
    const raw = [...m.entries()].sort((a, b) => a[0] - b[0]).map(([strike, iv]) => ({ strike, iv }))
    return cleanSmile(raw)
  }, [smile.data])

  const d = smile.data
  const spot = d?.spot ?? null
  const forward = d?.forward ?? null
  const atmPct = d?.atm_iv != null ? d.atm_iv * 100 : null
  const strikes = pts.map((p) => p.strike)
  const xmin = strikes.length ? Math.min(...strikes) : 0
  const xmax = strikes.length ? Math.max(...strikes) : 1

  const smileTrace = {
    type: 'scatter', mode: 'lines', name: 'Market smile',
    x: strikes, y: pts.map((p) => p.iv * 100),
    line: { color: c.accent, width: 2.5, shape: 'spline', smoothing: 1.0 },
    fill: 'tozeroy', fillcolor: cssVar('--accent-soft'),
    hovertemplate: 'K %{x}<br>IV %{y:.1f}%<extra></extra>',
  }
  const benchTrace = atmPct != null ? {
    type: 'scatter', mode: 'lines', name: 'Black-Scholes flat vol',
    x: [xmin, xmax], y: [atmPct, atmPct],
    line: { color: c.muted, dash: 'dash', width: 1.5 },
    hovertemplate: 'BS flat %{y:.1f}%<extra></extra>',
  } : null
  const wingTrace = d?.call_25 && d?.put_25 ? {
    type: 'scatter', mode: 'markers', name: '25Δ wings',
    x: [d.put_25.strike, d.call_25.strike], y: [d.put_25.iv * 100, d.call_25.iv * 100],
    marker: { color: c.neg, size: 8, symbol: 'diamond' },
    hovertemplate: '25Δ K %{x}: %{y:.1f}%<extra></extra>',
  } : null
  const atmTrace = forward != null && atmPct != null ? {
    type: 'scatter', mode: 'markers', name: 'ATM (forward)',
    x: [forward], y: [atmPct],
    marker: { color: c.accent, size: 11, line: { color: c.text, width: 1.5 } },
    hovertemplate: 'ATM at forward: %{y:.1f}%<extra></extra>',
  } : null

  const yvals = pts.map((p) => p.iv * 100)
  const ymin = yvals.length ? Math.max(0, Math.min(...yvals) - 3) : 0
  const ymax = yvals.length ? Math.max(...yvals) + 4 : 100
  const layout = {
    ...baseLayout(), height: 460, showlegend: true,
    legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    xaxis: { ...baseLayout().xaxis, title: { text: 'Strike' } },
    yaxis: { ...baseLayout().yaxis, title: { text: 'Implied volatility %' }, range: [ymin, ymax] },
    shapes: [
      forward != null ? { type: 'line', x0: forward, x1: forward, y0: 0, y1: 1, yref: 'paper', line: { color: c.accent, dash: 'dot', width: 1 } } : null,
      spot != null ? { type: 'line', x0: spot, x1: spot, y0: 0, y1: 1, yref: 'paper', line: { color: c.muted, dash: 'dot', width: 1 } } : null,
    ].filter(Boolean),
    annotations: [
      forward != null ? { x: forward, y: 1, yref: 'paper', text: 'forward', showarrow: false, font: { color: c.accent, size: 10 }, yanchor: 'bottom', xanchor: 'left' } : null,
      spot != null && Math.abs((spot ?? 0) - (forward ?? 0)) > (xmax - xmin) * 0.01 ? { x: spot, y: 1, yref: 'paper', text: 'spot', showarrow: false, font: { color: c.muted, size: 10 }, yanchor: 'bottom', xanchor: 'right' } : null,
    ].filter(Boolean),
  }
  const chartData = [benchTrace, smileTrace, wingTrace, atmTrace].filter(Boolean)

  return (
    <div>
      <div className="exps">
        {(exps.data?.expirations ?? []).slice(0, 14).map((e) => (
          <button key={e} className={e === exp ? 'active' : ''} onClick={() => setExp(e)}>{e}</button>
        ))}
      </div>

      {d && (
        <div className="stat-row">
          <div className="stat"><span className="lbl">ATM implied vol</span><span className="val">{pct(d.atm_iv)}</span></div>
          <div className="stat"><span className="lbl">Forward</span><span className="val">{money(forward)}</span></div>
          <div className="stat">
            <span className="lbl">25Δ risk reversal</span>
            <span className={`val ${d.rr_25 != null ? (d.rr_25 < 0 ? 'neg' : 'pos') : ''}`}>{volPts(d.rr_25)}</span>
          </div>
          <div className="stat"><span className="lbl">25Δ butterfly</span><span className="val">{volPts(d.bf_25)}</span></div>
        </div>
      )}
      {d && <div className="verdict" style={{ marginBottom: 12 }}>{interpretSmile(d.rr_25, d.bf_25)}</div>}

      <div className="chart-card">
        {smile.isLoading && <Loading label="Loading smile…" />}
        {smile.isError && <Failed error={smile.error} />}
        {d && (
          <Plot key={themeKey} data={chartData} layout={layout} config={plotConfig}
            style={{ width: '100%', height: 460 }} useResizeHandler />
        )}
      </div>
    </div>
  )
}

function RealizedTab({ ticker, themeKey }: { ticker: string; themeKey: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['rvi', ticker], queryFn: () => api.realizedVsImplied(ticker),
  })
  const c = plotColors()

  if (isLoading) return <Loading label={`Loading realized vs implied for ${ticker}…`} />
  if (isError) return <Failed error={error} />
  if (!data) return null

  const rv = data.realized_vol
  const atm = data.atm_iv
  const cats = ['RV 10d', 'RV 20d', 'RV 30d', 'RV 60d', 'ATM IV']
  const vals = [rv['10'], rv['20'], rv['30'], rv['60'], atm].map((v) => (v ? v * 100 : null))
  const barColors = [c.muted, c.muted, c.muted, c.muted, c.accent]

  const rv20 = rv['20']
  let verdict: React.ReactNode = <span className="dim">Not enough data to compare.</span>
  if (atm && rv20) {
    if (atm > rv20 * 1.05) verdict = <>Implied above realized. Options look <b className="rich">rich</b>.</>
    else if (atm < rv20 * 0.95) verdict = <>Implied below realized. Options look <b className="cheap">cheap</b>.</>
    else verdict = <>Implied is roughly in line with realized.</>
  }

  const layout = {
    ...baseLayout(), height: 340,
    yaxis: { ...baseLayout().yaxis, title: { text: 'Annualized %' }, rangemode: 'tozero' },
    xaxis: { ...baseLayout().xaxis },
    bargap: 0.45,
  }
  const trace = {
    type: 'bar', x: cats, y: vals, marker: { color: barColors },
    text: vals.map((v) => (v ? v.toFixed(1) + '%' : '')), textposition: 'outside',
    textfont: { color: c.text }, hovertemplate: '%{x}: %{y:.1f}%<extra></extra>',
  }

  return (
    <div>
      <div className="stat-row">
        <div className="stat">
          <span className="lbl">ATM implied vol</span>
          <span className="val">{pct(atm)}</span>
        </div>
        {data.iv_rank && (
          <div className="stat rank">
            <span className="lbl">IV rank · RV proxy</span>
            <span className="val">{data.iv_rank.rank.toFixed(0)}
              <span className="dim" style={{ fontSize: 12 }}> / {data.iv_rank.percentile.toFixed(0)}p</span>
            </span>
            <div className="bar"><i style={{ width: `${Math.max(2, Math.min(100, data.iv_rank.rank))}%` }} /></div>
          </div>
        )}
        <div className="stat">
          <span className="lbl">Realized 20d</span>
          <span className="val">{pct(rv20)}</span>
        </div>
      </div>
      <div className="verdict" style={{ marginBottom: 14 }}>{verdict}</div>
      <div className="chart-card">
        <Plot key={themeKey} data={[trace]} layout={layout} config={plotConfig}
          style={{ width: '100%', height: 340 }} useResizeHandler />
        <div className="chart-note">
          Realized volatility uses close-to-close returns; implied uses the at-the-money option (exp {data.atm_expiration}).
        </div>
      </div>
    </div>
  )
}
