import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api } from '../api'
import { pct, money } from '../format'
import { baseLayout, plotColors, ivColorscale, cssVar, plotConfig } from '../plotTheme'

type Tab = 'surface' | 'smile' | 'realized'

// Linear interpolation of a sorted [strike, iv] smile onto an arbitrary strike.
// This is the only interpolation used and it is structural: a 3D surface needs a
// grid, and the market only quotes discrete strikes. No smoothing is applied.
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
      if (spot && (p.strike < spot * 0.8 || p.strike > spot * 1.2)) continue
      const arr = byTenor.get(p.tenor) ?? []
      arr.push({ strike: p.strike, iv: p.iv })
      byTenor.set(p.tenor, arr)
    }
    const tenors = [...byTenor.keys()].sort((a, b) => a - b)
    if (tenors.length < 2) return null
    for (const t of tenors) byTenor.get(t)!.sort((a, b) => a.strike - b.strike)
    const all = [...byTenor.values()].flat().map((p) => p.strike)
    const lo = Math.min(...all), hi = Math.max(...all)
    const N = 48
    const strikes = Array.from({ length: N }, (_, i) => lo + ((hi - lo) * i) / (N - 1))
    const z = tenors.map((t) => {
      const pts = byTenor.get(t)!
      return strikes.map((s) => { const v = lerp(pts, s); return v == null ? null : v * 100 })
    })
    return { strikes, tenors, z }
  }, [data])

  if (isLoading) return <Loading label={`Loading surface for ${ticker}…`} />
  if (isError) return <Failed error={error} />
  if (!grid) return <div className="chart-card"><div className="msg">Not enough surface data.</div></div>

  const trace = {
    type: 'surface',
    x: grid.strikes, y: grid.tenors, z: grid.z,
    colorscale: ivColorscale(), showscale: true, opacity: 1,
    colorbar: {
      title: { text: 'IV %', side: 'right' }, titlefont: { color: c.muted },
      tickfont: { color: c.muted }, outlinecolor: c.grid, thickness: 12, len: 0.6,
    },
    contours: { z: { show: true, usecolormap: true, width: 1.5 } },
    lighting: { ambient: 0.8, diffuse: 0.5, specular: 0.08, roughness: 0.85, fresnel: 0.1 },
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
      camera: { eye: { x: 1.5, y: -1.7, z: 0.5 } },
      aspectratio: { x: 1.6, y: 0.9, z: 0.6 },
    },
  }
  return (
    <div className="chart-card">
      <Plot key={themeKey} data={[trace]} layout={layout} config={plotConfig}
        style={{ width: '100%', height: 580 }} useResizeHandler />
      <div className="chart-note">
        IV across strike and expiration (near-money band), linearly interpolated to a grid with contour lines. Drag to rotate, scroll to zoom.
      </div>
    </div>
  )
}

function SmileTab({ ticker, ivSource, themeKey }: { ticker: string; ivSource: string; themeKey: string }) {
  const exps = useQuery({ queryKey: ['exps', ticker], queryFn: () => api.expirations(ticker) })
  const [exp, setExp] = useState<string | null>(null)
  useEffect(() => {
    if (exps.data && (!exp || !exps.data.expirations.includes(exp))) {
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

  // The actual per-strike implied vols, no smoothing. One value per strike.
  const pts = useMemo(() => {
    if (!smile.data) return [] as { strike: number; iv: number }[]
    const m = new Map<number, number>()
    for (const p of smile.data.points) {
      if (p.iv > 0 && !m.has(p.strike)) m.set(p.strike, p.iv)
    }
    return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([strike, iv]) => ({ strike, iv }))
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
    line: { color: c.accent, width: 2 },
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
    marker: { color: c.neg, size: 10, symbol: 'diamond' },
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
    ...baseLayout(), height: 470, showlegend: true,
    margin: { l: 58, r: 18, t: 12, b: 70 },
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: -0.24, yanchor: 'top',
      bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    xaxis: { ...baseLayout().xaxis, title: { text: 'Strike' } },
    yaxis: { ...baseLayout().yaxis, title: { text: 'Implied volatility %' }, range: [ymin, ymax] },
    shapes: [
      forward != null ? { type: 'line', x0: forward, x1: forward, y0: 0, y1: 1, yref: 'paper', line: { color: c.accent, dash: 'dot', width: 1 } } : null,
      spot != null ? { type: 'line', x0: spot, x1: spot, y0: 0, y1: 1, yref: 'paper', line: { color: c.muted, dash: 'dot', width: 1 } } : null,
    ].filter(Boolean),
    annotations: [
      forward != null ? { x: forward, y: 1, yref: 'paper', text: 'Forward', showarrow: false, font: { color: c.accent, size: 10 }, yanchor: 'bottom', xanchor: 'left' } : null,
      spot != null ? { x: spot, y: 0.94, yref: 'paper', text: 'Spot', showarrow: false, font: { color: c.muted, size: 10 }, yanchor: 'bottom', xanchor: 'right' } : null,
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
            style={{ width: '100%', height: 470 }} useResizeHandler />
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

  const atm = data.atm_iv
  const gk = data.realized_vol_gk
  const cc = data.realized_vol_cc
  const gk20 = gk['20']
  const wins = ['10', '20', '30', '60']

  let verdict: React.ReactNode = <span className="dim">Not enough data to compare.</span>
  if (atm && gk20) {
    if (atm > gk20 * 1.05) verdict = <>Implied above realized. Options look <b className="rich">rich</b>.</>
    else if (atm < gk20 * 0.95) verdict = <>Implied below realized. Options look <b className="cheap">cheap</b>.</>
    else verdict = <>Implied is roughly in line with realized.</>
  }

  const dv = data.divergence
  let divergenceNote: React.ReactNode = null
  if (dv) {
    const apart = (dv.rel_diff * 100).toFixed(0)
    const dir = dv.gk_below_cc ? 'below' : 'above'
    divergenceNote = (
      <div className="verdict" style={{ marginBottom: 12 }}>
        Garman-Klass {(dv.gk * 100).toFixed(1)}% vs close-to-close {(dv.cc * 100).toFixed(1)}% ({apart}% apart), GK sits {dir}.
        {dv.flag
          ? <> <b className="rich">Substantial divergence</b>: large intraday moves relative to closes, or overnight gaps understating Garman-Klass.</>
          : dv.gk_below_cc ? ' Consistent with overnight gaps, which Garman-Klass does not capture.' : ''}
      </div>
    )
  }

  // Bars: realized (Garman-Klass primary, close-to-close secondary); ATM implied as a line.
  const barLayout = {
    ...baseLayout(), height: 320, barmode: 'group', showlegend: true,
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.12, yanchor: 'bottom',
      bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    margin: { l: 52, r: 18, t: 34, b: 34 },
    yaxis: { ...baseLayout().yaxis, title: { text: 'Annualized %' }, rangemode: 'tozero' },
    shapes: atm ? [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: atm * 100, y1: atm * 100,
      line: { color: c.text, dash: 'dash', width: 1.5 } }] : [],
    annotations: atm ? [{ xref: 'paper', x: 0.995, y: atm * 100, text: `ATM implied ${(atm * 100).toFixed(1)}%`,
      showarrow: false, font: { color: c.text, size: 11 }, xanchor: 'right', yanchor: 'bottom' }] : [],
  }
  const barData = [
    { type: 'bar', name: 'Garman-Klass', x: wins.map((w) => w + 'd'),
      y: wins.map((w) => (gk[w] ? gk[w]! * 100 : null)), marker: { color: c.accent },
      hovertemplate: 'GK %{x}: %{y:.1f}%<extra></extra>' },
    { type: 'bar', name: 'Close-to-close', x: wins.map((w) => w + 'd'),
      y: wins.map((w) => (cc[w] ? cc[w]! * 100 : null)), marker: { color: c.muted },
      hovertemplate: 'C2C %{x}: %{y:.1f}%<extra></extra>' },
  ]

  // Volatility cone: percentile bands of historical realized (GK) per window, today overlaid.
  const coneWins = wins.map(Number)
  const cone = data.cone
  const band = (key: 'min' | 'p25' | 'median' | 'p75' | 'max' | 'current') =>
    wins.map((w) => { const b = cone[w]; return b ? b[key] * 100 : null })
  const coneData = [
    { type: 'scatter', mode: 'lines', x: coneWins, y: band('min'), line: { width: 0 }, showlegend: false, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', name: 'min–max', x: coneWins, y: band('max'), line: { width: 0 }, fill: 'tonexty', fillcolor: 'rgba(140,140,150,0.10)', hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', x: coneWins, y: band('p25'), line: { width: 0 }, showlegend: false, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', name: '25–75%', x: coneWins, y: band('p75'), line: { width: 0 }, fill: 'tonexty', fillcolor: 'rgba(140,140,150,0.20)', hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', name: 'median', x: coneWins, y: band('median'), line: { color: c.muted, dash: 'dot', width: 1.5 }, hovertemplate: 'median %{y:.1f}%<extra></extra>' },
    { type: 'scatter', mode: 'lines+markers', name: 'current', x: coneWins, y: band('current'), line: { color: c.accent, width: 2 }, marker: { size: 8, color: c.accent }, hovertemplate: 'current %{x}d: %{y:.1f}%<extra></extra>' },
  ]
  const coneLayout = {
    ...baseLayout(), height: 340, showlegend: true,
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.12, yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    margin: { l: 52, r: 18, t: 34, b: 44 },
    xaxis: { ...baseLayout().xaxis, title: { text: 'Realized-vol window (days)' }, tickvals: coneWins },
    yaxis: { ...baseLayout().yaxis, title: { text: 'Garman-Klass vol %' }, rangemode: 'tozero' },
  }

  return (
    <div>
      <div className="stat-row">
        <div className="stat"><span className="lbl">ATM implied vol</span><span className="val">{pct(atm)}</span></div>
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
          <span className="lbl">Vol risk premium (20d)</span>
          <span className={`val ${data.vrp ? (data.vrp.spread >= 0 ? 'pos' : 'neg') : ''}`}>{volPts(data.vrp?.spread)}</span>
        </div>
        <div className="stat">
          <span className="lbl">Implied / realized</span>
          <span className="val">{data.vrp ? data.vrp.ratio.toFixed(2) + '×' : '—'}</span>
        </div>
      </div>

      <div className="verdict" style={{ marginBottom: 12 }}>{verdict}</div>
      {divergenceNote}

      <div className="chart-card" style={{ marginBottom: 14 }}>
        <Plot key={themeKey + 'bar'} data={barData} layout={barLayout} config={plotConfig}
          style={{ width: '100%', height: 320 }} useResizeHandler />
        <div className="chart-note">
          Realized volatility, Garman-Klass primary (open-high-low-close) and close-to-close for comparison, against the at-the-money implied line. Garman-Klass understates vol when the underlying gaps between sessions.
        </div>
      </div>

      <div className="chart-card">
        <div className="lbl" style={{ marginBottom: 6 }}>Realized-vol cone (Garman-Klass, 1-year history)</div>
        <Plot key={themeKey + 'cone'} data={coneData} layout={coneLayout} config={plotConfig}
          style={{ width: '100%', height: 340 }} useResizeHandler />
        <div className="chart-note">
          Percentile bands of realized volatility at each window over the past year, with today's values overlaid. Shows whether current realized is high or low by the name's own history.
        </div>
      </div>
    </div>
  )
}
