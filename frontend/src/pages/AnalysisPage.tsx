import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api } from '../api'
import { pct } from '../format'
import { baseLayout, plotColors, ivColorscale, plotConfig } from '../plotTheme'

type Tab = 'surface' | 'smile' | 'realized'

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

  const trace = useMemo(() => {
    if (!data) return null
    const spot = data.spot ?? 0
    // Focus on the liquid, near-money region so the z-axis is not blown out by
    // short-dated wing IV.
    const pts = data.points.filter(
      (p) => p.iv > 0 && p.iv <= 0.8 && (!spot || (p.strike >= spot * 0.75 && p.strike <= spot * 1.25)),
    )
    return {
      type: 'mesh3d',
      x: pts.map((p) => p.strike),
      y: pts.map((p) => p.tenor),
      z: pts.map((p) => p.iv * 100),
      intensity: pts.map((p) => p.iv * 100),
      colorscale: ivColorscale(),
      opacity: 0.9,
      showscale: true,
      colorbar: { title: 'IV %', tickfont: { color: c.muted }, outlinecolor: c.grid, thickness: 10, len: 0.55 },
      hovertemplate: 'K %{x}<br>T %{y:.2f}y<br>IV %{z:.1f}%<extra></extra>',
    }
  }, [data, c.muted, c.grid])

  if (isLoading) return <Loading label={`Loading surface for ${ticker}…`} />
  if (isError) return <Failed error={error} />
  if (!trace) return null

  const axis = { color: c.muted, gridcolor: c.grid, showbackground: false, zerolinecolor: c.grid }
  const layout = {
    ...baseLayout(),
    height: 560,
    scene: {
      xaxis: { ...axis, title: { text: 'Strike' } },
      yaxis: { ...axis, title: { text: 'Tenor (yrs)' } },
      zaxis: { ...axis, title: { text: 'IV %' } },
      camera: { eye: { x: 1.7, y: -1.5, z: 0.7 } },
    },
  }
  return (
    <div className="chart-card">
      <Plot key={themeKey} data={[trace]} layout={layout} config={plotConfig}
        style={{ width: '100%', height: 560 }} useResizeHandler />
      <div className="chart-note">
        IV surface across strike and expiration, near-money band. Drag to rotate, scroll to zoom.
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
    if (!smile.data) return [] as [number, number][]
    const m = new Map<number, number>()
    for (const p of smile.data.points) {
      if (p.iv > 0 && p.iv <= 1.0 && !m.has(p.strike)) m.set(p.strike, p.iv)
    }
    return [...m.entries()].sort((a, b) => a[0] - b[0])
  }, [smile.data])

  const spot = smile.data?.spot ?? null
  const trace = {
    type: 'scatter', mode: 'lines+markers',
    x: pts.map((p) => p[0]), y: pts.map((p) => p[1] * 100),
    line: { color: c.accent, width: 2 }, marker: { size: 4, color: c.accent },
    hovertemplate: 'K %{x}<br>IV %{y:.1f}%<extra></extra>',
  }
  const layout = {
    ...baseLayout(), height: 460,
    xaxis: { ...baseLayout().xaxis, title: 'Strike' },
    yaxis: { ...baseLayout().yaxis, title: 'Implied volatility %' },
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
            style={{ width: '100%', height: 460 }} useResizeHandler />
        )}
        <div className="chart-note">IV vs strike for {exp}. Call and put IV are reconciled to one value per strike.</div>
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
    yaxis: { ...baseLayout().yaxis, title: 'Annualized %', rangemode: 'tozero' },
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
