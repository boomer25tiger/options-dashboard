import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api } from '../api'
import { pct } from '../format'
import { baseLayout, plotColors, ivColorscale, cssVar, plotConfig } from '../plotTheme'

type Tab = 'surface' | 'smile' | 'realized'

// Linear interpolation of a sorted [strike, iv] smile onto an arbitrary strike.
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

// 3-point moving average over defined values (smooths grid rows).
function smoothRow(row: (number | null)[]): (number | null)[] {
  return row.map((v, i) => {
    if (v == null) return null
    const w = [row[i - 1], v, row[i + 1]].filter((x): x is number => x != null)
    return w.reduce((s, x) => s + x, 0) / w.length
  })
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
      return smoothRow(strikes.map((s) => { const v = lerp(pts, s); return v == null ? null : v * 100 }))
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
    colorbar: { title: 'IV %', tickfont: { color: c.muted }, outlinecolor: c.grid, thickness: 10, len: 0.55 },
    lighting: { ambient: 0.78, diffuse: 0.5, specular: 0.12, roughness: 0.55, fresnel: 0.15 },
    lightposition: { x: 120, y: 220, z: 320 },
    contours: { z: { show: true, usecolormap: true, project: { z: true }, width: 1 } },
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
      camera: { eye: { x: 1.5, y: -1.65, z: 0.55 } },
      aspectratio: { x: 1.5, y: 1, z: 0.7 },
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
    if (exps.data && (!exp || !exps.data.expirations.includes(exp))) setExp(exps.data.expirations[0] ?? null)
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
      if (p.iv > 0 && p.iv <= 1.0 && !m.has(p.strike)) m.set(p.strike, p.iv)
    }
    const raw = [...m.entries()].sort((a, b) => a[0] - b[0]).map(([strike, iv]) => ({ strike, iv }))
    // Drop spikes: a point that deviates sharply from its neighbours' average.
    return raw.filter((p, i) => {
      if (i === 0 || i === raw.length - 1) return true
      const nb = (raw[i - 1].iv + raw[i + 1].iv) / 2
      return Math.abs(p.iv - nb) < nb * 0.5
    })
  }, [smile.data])

  const spot = smile.data?.spot ?? null
  const trace = {
    type: 'scatter', mode: 'lines',
    x: pts.map((p) => p.strike), y: pts.map((p) => p.iv * 100),
    line: { color: c.accent, width: 2.5, shape: 'spline', smoothing: 1.0 },
    fill: 'tozeroy', fillcolor: cssVar('--accent-soft'),
    hovertemplate: 'K %{x}<br>IV %{y:.1f}%<extra></extra>',
  }
  const ys = pts.map((p) => p.iv * 100)
  const ymin = ys.length ? Math.max(0, Math.min(...ys) - 3) : 0
  const ymax = ys.length ? Math.max(...ys) + 3 : 100
  const layout = {
    ...baseLayout(), height: 470,
    xaxis: { ...baseLayout().xaxis, title: { text: 'Strike' } },
    yaxis: { ...baseLayout().yaxis, title: { text: 'Implied volatility %' }, range: [ymin, ymax] },
    shapes: spot ? [{ type: 'line', x0: spot, x1: spot, y0: 0, y1: 1, yref: 'paper',
      line: { color: c.muted, dash: 'dot', width: 1 } }] : [],
    annotations: spot ? [{ x: spot, y: 1, yref: 'paper', text: 'spot', showarrow: false,
      font: { color: c.muted, size: 10 }, yanchor: 'bottom' }] : [],
  }

  return (
    <div>
      <div className="exps">
        {(exps.data?.expirations ?? []).slice(0, 12).map((e) => (
          <button key={e} className={e === exp ? 'active' : ''} onClick={() => setExp(e)}>{e}</button>
        ))}
      </div>
      <div className="chart-card">
        {smile.isLoading && <Loading label="Loading smile…" />}
        {smile.isError && <Failed error={smile.error} />}
        {smile.data && (
          <Plot key={themeKey} data={[trace]} layout={layout} config={plotConfig}
            style={{ width: '100%', height: 470 }} useResizeHandler />
        )}
        <div className="chart-note">Implied vol vs strike for {exp}, spline-smoothed with spikes removed. Spot marked.</div>
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
