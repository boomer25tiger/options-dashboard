import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api, type HestonCalibration } from '../api'
import { pct, money } from '../format'
import { baseLayout, plotColors, ivColorscale, cssVar, plotConfig } from '../plotTheme'

type Tab = 'surface' | 'smile' | 'realized' | 'hedge'

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
        <button className={tab === 'hedge' ? 'active' : ''} onClick={() => setTab('hedge')}>Delta Hedging</button>
      </div>
      {tab === 'surface' && <SurfaceTab ticker={ticker} ivSource={ivSource} themeKey={theme} />}
      {tab === 'smile' && <SmileTab ticker={ticker} ivSource={ivSource} themeKey={theme} />}
      {tab === 'realized' && <RealizedTab ticker={ticker} themeKey={theme} />}
      {tab === 'hedge' && <HedgingTab ticker={ticker} themeKey={theme} />}
    </div>
  )
}

function Loading({ label }: { label: string }) {
  return <div className="msg"><span className="spin" />{label}</div>
}
function Failed({ error }: { error: unknown }) {
  return <div className="msg err">Failed to load: {(error as Error).message}</div>
}

function HedgingTab({ ticker, themeKey }: { ticker: string; themeKey: string }) {
  const [lookback, setLookback] = useState(30)
  const [position, setPosition] = useState(1)
  const [optionType, setOptionType] = useState<'call' | 'put'>('call')
  const [ivPct, setIvPct] = useState('')
  const c = plotColors()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['hedge', ticker, lookback, position, optionType, ivPct],
    queryFn: () => api.hedge(ticker, {
      lookback, position, optionType,
      impliedVol: ivPct.trim() ? Number(ivPct) / 100 : undefined,
    }),
  })

  const inputStyle = { width: 92, padding: '5px 8px', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 3, color: 'var(--text)', fontFamily: 'var(--mono)', fontSize: 13, outline: 'none' }
  const controls = (
    <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 14 }}>
      <div>
        <div className="lbl" style={{ marginBottom: 4 }}>Window</div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[20, 30, 60, 90].map((d) => <button key={d} className={`btn ${lookback === d ? 'accent' : ''}`} onClick={() => setLookback(d)}>{d}d</button>)}
        </div>
      </div>
      <div>
        <div className="lbl" style={{ marginBottom: 4 }}>Position</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className={`btn ${position === 1 ? 'accent' : ''}`} onClick={() => setPosition(1)}>Long</button>
          <button className={`btn ${position === -1 ? 'accent' : ''}`} onClick={() => setPosition(-1)}>Short</button>
        </div>
      </div>
      <div>
        <div className="lbl" style={{ marginBottom: 4 }}>Option</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className={`btn ${optionType === 'call' ? 'accent' : ''}`} onClick={() => setOptionType('call')}>Call</button>
          <button className={`btn ${optionType === 'put' ? 'accent' : ''}`} onClick={() => setOptionType('put')}>Put</button>
        </div>
      </div>
      <div>
        <div className="lbl" style={{ marginBottom: 4 }}>Implied vol %</div>
        <input value={ivPct} onChange={(e) => setIvPct(e.target.value)} placeholder="1m ATM" style={inputStyle} />
      </div>
    </div>
  )

  if (isLoading) return <div>{controls}<Loading label={`Simulating the hedge for ${ticker}…`} /></div>
  if (isError) return <div>{controls}<Failed error={error} /></div>
  if (!data) return <div>{controls}</div>

  const s = data.summary
  const x = data.steps.map((st) => st.date)
  const chartData = [
    { type: 'scatter', mode: 'lines', name: 'Hedge P&L', x, y: data.steps.map((st) => st.cum_pnl),
      line: { color: c.accent, width: 2 }, hovertemplate: 'P&L $%{y:,.0f}<extra></extra>' },
    { type: 'scatter', mode: 'lines', name: 'Underlying', x, y: data.steps.map((st) => st.spot), yaxis: 'y2',
      line: { color: c.muted, width: 1.5, dash: 'dot' }, hovertemplate: 'spot %{y:.2f}<extra></extra>' },
  ]
  const layout = {
    ...baseLayout(), height: 380, showlegend: true, hovermode: 'x unified',
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.12, yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    margin: { l: 62, r: 56, t: 34, b: 40 },
    xaxis: { ...baseLayout().xaxis },
    yaxis: { ...baseLayout().yaxis, title: { text: 'Cumulative P&L $' } },
    yaxis2: { overlaying: 'y', side: 'right', title: { text: 'Underlying' }, gridcolor: 'rgba(0,0,0,0)', tickfont: { color: c.muted }, titlefont: { color: c.muted } },
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: c.grid, width: 1 } }],
  }

  const pnlClass = s.total_pnl >= 0 ? 'pos' : 'neg'
  return (
    <div>
      {controls}
      <div className="cards">
        <div className="card hl">
          <div className="lbl">Total hedge P&amp;L</div>
          <div className={`big ${pnlClass}`}>{money(s.total_pnl)}</div>
          <div className="sub">{s.days}d · {s.position >= 0 ? 'long' : 'short'} {s.option_type}</div>
        </div>
        <div className="card">
          <div className="lbl">Implied · hedged at</div>
          <div className="big">{pct(s.implied_vol)}</div>
          <div className="sub">held constant</div>
        </div>
        <div className="card">
          <div className="lbl">Realized · window</div>
          <div className="big">{pct(s.realized_vol)}</div>
          <div className="sub">{s.vol_spread != null ? `spread ${(s.vol_spread * 100).toFixed(1)} pts` : ''}</div>
        </div>
        <div className="card">
          <div className="lbl">Entry premium</div>
          <div className="big">{money(Math.abs(s.entry_premium))}</div>
          <div className="sub">{s.position >= 0 ? 'paid' : 'received'}</div>
        </div>
      </div>

      {data.read && (
        <div className="verdict" style={{ marginBottom: 12 }}>
          <b className={pnlClass}>{data.read.headline}.</b> {data.read.detail}
          <span className="dim"> {data.read.note}</span>
        </div>
      )}

      <div className="chart-card">
        <Plot key={themeKey + 'hedge'} data={chartData} layout={layout} config={plotConfig}
          style={{ width: '100%', height: 380 }} useResizeHandler />
        <div className="chart-note">
          Cumulative P&amp;L of delta-hedging the option day by day, with the underlying path dotted on the right axis. Each day's change is the gamma gain from realized movement net of the theta bleed.
        </div>
      </div>

      <div className="section-h">Gamma-theta split</div>
      <div className="kv-grid">
        <div className="kv2"><span className="lbl">Gamma gain</span><span className={`v ${s.gamma_pnl_total >= 0 ? 'pos' : 'neg'}`}>{money(s.gamma_pnl_total)}</span></div>
        <div className="kv2"><span className="lbl">Theta bleed</span><span className={`v ${s.theta_pnl_total >= 0 ? 'pos' : 'neg'}`}>{money(s.theta_pnl_total)}</span></div>
        <div className="kv2"><span className="lbl">Strike</span><span className="v">{money(s.strike)}</span></div>
      </div>
    </div>
  )
}

function HestonPanel({ calib, loading }: { calib?: HestonCalibration; loading: boolean }) {
  if (loading) return (
    <div className="chart-card" style={{ marginTop: 12 }}>
      <div className="msg"><span className="spin" />Calibrating Heston to the chain…</div>
    </div>
  )
  if (!calib) return null
  if (!calib.ok || !calib.params) return (
    <div className="chart-card" style={{ marginTop: 12 }}>
      <div className="msg">Heston calibration unavailable{calib.reason ? ` (${calib.reason})` : ''}.</div>
    </div>
  )
  const p = calib.params
  const vol = (v: number) => (Math.sqrt(v) * 100).toFixed(1) + '%'
  return (
    <div className="chart-card" style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 13 }}>Heston calibration</strong>
        <span className="dim" style={{ fontSize: 12 }}>
          fit {((calib.iv_rmse ?? 0) * 100).toFixed(1)} vol points across {calib.n_instruments} options · {calib.feller_ok ? 'Feller satisfied' : 'Feller violated'}
        </span>
      </div>
      <div className="kv-grid">
        <div className="kv2"><span className="lbl">Initial vol √v₀</span><span className="v">{vol(p.v0)}</span></div>
        <div className="kv2"><span className="lbl">Long-run vol √θ</span><span className="v">{vol(p.theta)}</span></div>
        <div className="kv2"><span className="lbl">Mean reversion κ</span><span className="v">{p.kappa.toFixed(2)}</span></div>
        <div className="kv2"><span className="lbl">Vol of vol ξ</span><span className="v">{p.xi.toFixed(2)}</span></div>
        <div className="kv2"><span className="lbl">Correlation ρ</span><span className="v">{p.rho.toFixed(2)}</span></div>
      </div>
      {calib.per_expiration && calib.per_expiration.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 10, maxHeight: 240, minHeight: 0 }}>
          <table className="chain">
            <thead>
              <tr>
                <th className="l">Expiration</th>
                <th>Tenor</th>
                <th>Options</th>
                <th>Fit (vol pts)</th>
              </tr>
            </thead>
            <tbody>
              {calib.per_expiration.map((pe) => (
                <tr key={pe.expiration}>
                  <td style={{ textAlign: 'left' }}>{pe.expiration}</td>
                  <td>{pe.tenor.toFixed(3)}y</td>
                  <td>{pe.n}</td>
                  <td>{(pe.iv_rmse * 100).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="chart-note">
        One stochastic-vol process fit to the whole chain across strikes and maturities. Negative ρ carries the equity skew, and √θ is the volatility the process reverts to. A single Heston cannot match every slice, so the fit error tends to widen at the long end.
      </div>
    </div>
  )
}

function SurfaceTab({ ticker, ivSource, themeKey }: { ticker: string; ivSource: string; themeKey: string }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['surface', ticker, ivSource],
    queryFn: () => api.surface(ticker, ivSource, 12),
  })
  const c = plotColors()
  const [sviOn, setSviOn] = useState(false)
  const [arbOn, setArbOn] = useState(true)
  const [hestonOn, setHestonOn] = useState(false)

  // Heston calibration is expensive, so it loads only when its overlay is on.
  const hestonQuery = useQuery({
    queryKey: ['heston', ticker],
    queryFn: () => api.heston(ticker),
    enabled: hestonOn,
    staleTime: 5 * 60 * 1000,
  })
  const calib = hestonQuery.data

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

  const sviGrid = useMemo(() => {
    if (!data) return null
    const spot = data.spot ?? 0
    const inBand = (K: number) => !spot || (K >= spot * 0.8 && K <= spot * 1.2)
    const fitted = data.svi.slices.filter((s) => s.ok && s.curve && s.curve.length >= 2)
    if (fitted.length < 2) return null
    const allK = fitted.flatMap((s) => s.curve!.map((p) => p.strike)).filter(inBand)
    if (allK.length < 2) return null
    const lo = Math.min(...allK), hi = Math.max(...allK)
    const N = 48
    const strikes = Array.from({ length: N }, (_, i) => lo + ((hi - lo) * i) / (N - 1))
    const tenors = fitted.map((s) => s.tenor)
    const z = fitted.map((s) => strikes.map((K) => { const iv = lerp(s.curve!, K); return iv == null ? null : iv * 100 }))
    return { strikes, tenors, z }
  }, [data])

  const rawScatter = useMemo(() => {
    if (!data) return null
    const spot = data.spot ?? 0
    const pts = data.points.filter((p) => p.iv > 0 && p.iv <= 0.8 && (!spot || (p.strike >= spot * 0.8 && p.strike <= spot * 1.2)))
    return { x: pts.map((p) => p.strike), y: pts.map((p) => p.tenor), z: pts.map((p) => p.iv * 100) }
  }, [data])

  const hestonMesh = useMemo(() => {
    const s = calib?.surface
    if (!calib?.ok || !s) return null
    return { x: s.strikes, y: s.tenors, z: s.z }
  }, [calib])

  const hestonPts = useMemo(() => {
    if (!calib?.points || !calib.spot) return null
    const spot = calib.spot
    const pts = calib.points.filter((p) => p.iv > 0 && p.iv <= 0.8 && p.strike >= spot * 0.8 && p.strike <= spot * 1.2)
    return { x: pts.map((p) => p.strike), y: pts.map((p) => p.tenor), z: pts.map((p) => p.iv * 100) }
  }, [calib])

  // Place a marker at each raw-surface arbitrage violation. Butterfly gives an
  // exact strike; calendar gives a log-moneyness, so approximate its strike from
  // spot. The height is the raw IV interpolated at that strike/expiration.
  const arbMarkers = useMemo(() => {
    if (!data) return null
    const spot = data.spot ?? 0
    const viol = data.arbitrage.violations
    if (!viol.length) return null
    const byExp = new Map<string, { strike: number; iv: number }[]>()
    for (const p of data.points) {
      if (!(p.iv > 0 && p.iv <= 0.8)) continue
      const a = byExp.get(p.expiration) ?? []
      a.push({ strike: p.strike, iv: p.iv })
      byExp.set(p.expiration, a)
    }
    for (const a of byExp.values()) a.sort((x, y) => x.strike - y.strike)
    const x: number[] = [], y: number[] = [], z: number[] = [], text: string[] = []
    for (const v of viol) {
      const K = v.strike != null ? v.strike : (spot && v.moneyness != null ? spot * Math.exp(v.moneyness) : null)
      if (K == null) continue
      const pts = byExp.get(v.expiration)
      const iv = pts ? lerp(pts, K) : null
      if (iv == null) continue
      x.push(K); y.push(v.tenor); z.push(iv * 100)
      text.push(v.type === 'butterfly' ? `Butterfly · K ${K.toFixed(0)}` : `Calendar · ${(v.moneyness ?? 0) >= 0 ? '+' : ''}${((v.moneyness ?? 0) * 100).toFixed(0)}% mny`)
    }
    return x.length ? { x, y, z, text } : null
  }, [data])

  if (isLoading) return <Loading label={`Loading surface for ${ticker}…`} />
  if (isError) return <Failed error={error} />
  if (!data) return null
  if (!grid) return <div className="chart-card"><div className="msg">Not enough surface data.</div></div>

  const colorbar = {
    title: { text: 'IV %', side: 'right' }, titlefont: { color: c.muted },
    tickfont: { color: c.muted }, outlinecolor: c.grid, thickness: 12, len: 0.6,
  }
  const rawSurface = {
    type: 'surface', x: grid.strikes, y: grid.tenors, z: grid.z,
    colorscale: ivColorscale(), showscale: true, opacity: 1, colorbar,
    contours: { z: { show: true, usecolormap: true, width: 1.5 } },
    lighting: { ambient: 0.8, diffuse: 0.5, specular: 0.08, roughness: 0.85, fresnel: 0.1 },
    lightposition: { x: 100, y: 200, z: 350 },
    hovertemplate: 'K %{x:.0f}<br>T %{y:.3f}y<br>IV %{z:.1f}%<extra></extra>',
  }
  const sviSurface = sviGrid ? {
    type: 'surface', x: sviGrid.strikes, y: sviGrid.tenors, z: sviGrid.z,
    colorscale: ivColorscale(), showscale: true, opacity: 0.82, colorbar,
    contours: { z: { show: true, usecolormap: true, width: 1.5 } },
    lighting: { ambient: 0.85, diffuse: 0.45, specular: 0.06, roughness: 0.9 },
    lightposition: { x: 100, y: 200, z: 350 },
    hovertemplate: 'K %{x:.0f}<br>T %{y:.3f}y<br>IV %{z:.1f}% (fit)<extra></extra>',
  } : null
  const rawPts = rawScatter ? {
    type: 'scatter3d', mode: 'markers', x: rawScatter.x, y: rawScatter.y, z: rawScatter.z,
    marker: { size: 1.8, color: c.text, opacity: 0.55 },
    hovertemplate: 'K %{x:.0f}<br>T %{y:.3f}y<br>IV %{z:.1f}% (raw)<extra></extra>',
  } : null
  const arbTrace = arbMarkers ? {
    type: 'scatter3d', mode: 'markers', x: arbMarkers.x, y: arbMarkers.y, z: arbMarkers.z,
    marker: { size: 5, color: c.neg, symbol: 'x', line: { color: c.neg, width: 1 } },
    text: arbMarkers.text,
    hovertemplate: '%{text}<br>IV %{z:.1f}%<extra>arbitrage</extra>',
  } : null

  const hestonSurfaceTrace = hestonMesh ? {
    type: 'surface', x: hestonMesh.x, y: hestonMesh.y, z: hestonMesh.z,
    colorscale: ivColorscale(), showscale: true, opacity: 0.85, colorbar,
    contours: { z: { show: true, usecolormap: true, width: 1.5 } },
    lighting: { ambient: 0.85, diffuse: 0.45, specular: 0.06, roughness: 0.9 },
    lightposition: { x: 100, y: 200, z: 350 },
    hovertemplate: 'K %{x:.0f}<br>T %{y:.3f}y<br>IV %{z:.1f}% (Heston)<extra></extra>',
  } : null
  const hestonPtsTrace = hestonPts ? {
    type: 'scatter3d', mode: 'markers', x: hestonPts.x, y: hestonPts.y, z: hestonPts.z,
    marker: { size: 1.8, color: c.text, opacity: 0.55 },
    hovertemplate: 'K %{x:.0f}<br>T %{y:.3f}y<br>IV %{z:.1f}% (raw)<extra></extra>',
  } : null

  const showHeston = hestonOn && !!hestonSurfaceTrace
  const showSvi = sviOn && !showHeston && !!sviSurface
  const showArb = arbOn && !showHeston && !!arbTrace
  const base = showHeston
    ? [hestonSurfaceTrace, hestonPtsTrace].filter(Boolean)
    : showSvi ? [sviSurface, rawPts].filter(Boolean) : [rawSurface]
  const traces = showArb ? [...base, arbTrace] : base

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
  const fittedCount = data.svi.slices.filter((s) => s.ok).length
  const totalSlices = data.svi.slices.length
  const arb = data.arbitrage
  const violations = arb.violations
  const arbTotal = arb.counts.butterfly + arb.counts.calendar

  // ATM term structure: ATM vol by maturity. Linked to the SVI toggle — when the
  // overlay is on and slices calibrated, the line follows the smoother fitted ATM;
  // otherwise it follows the raw ATM interpolated at each forward.
  const termPts = [...data.term_structure.points].sort((a, b) => a.tenor - b.tenor)
  const hasTerm = termPts.filter((p) => p.atm_raw != null).length >= 2
  const hasSviAtm = termPts.some((p) => p.atm_svi != null)
  const useSviLine = sviOn && hasSviAtm
  const termX = termPts.map((p) => p.tenor)
  const termText = termPts.map((p) => p.expiration)
  const termLineY = termPts.map((p) => {
    const v = useSviLine ? (p.atm_svi ?? p.atm_raw) : p.atm_raw
    return v != null ? v * 100 : null
  })
  const termRawY = termPts.map((p) => (p.atm_raw != null ? p.atm_raw * 100 : null))
  const termData = [
    {
      type: 'scatter', mode: 'lines+markers', name: useSviLine ? 'SVI ATM' : 'ATM IV',
      x: termX, y: termLineY, text: termText, connectgaps: true,
      line: { color: c.accent, width: 2, shape: useSviLine ? 'spline' : 'linear' },
      marker: { color: c.accent, size: 7 },
      hovertemplate: '%{text}<br>T %{x:.3f}y<br>ATM IV %{y:.2f}%<extra></extra>',
    },
    ...(useSviLine ? [{
      type: 'scatter', mode: 'markers', name: 'raw ATM',
      x: termX, y: termRawY, text: termText,
      marker: { color: c.muted, size: 5, symbol: 'circle-open' },
      hovertemplate: '%{text}<br>raw ATM %{y:.2f}%<extra></extra>',
    }] : []),
  ]
  const termLayout = {
    ...baseLayout(), height: 300, showlegend: useSviLine,
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.12, yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    xaxis: { ...baseLayout().xaxis, title: { text: 'Time to expiry (years)' } },
    yaxis: { ...baseLayout().yaxis, title: { text: 'ATM implied vol %' } },
  }

  return (
    <>
    <div className="chart-card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6, flexWrap: 'wrap' }}>
        <button className={`btn ${sviOn ? 'accent' : ''}`} onClick={() => { setSviOn((v) => !v); setHestonOn(false) }}>
          SVI fit overlay {sviOn ? 'on' : 'off'}
        </button>
        <button className={`btn ${hestonOn ? 'accent' : ''}`} onClick={() => { setHestonOn((v) => !v); setSviOn(false) }}>
          Heston fit {hestonOn ? 'on' : 'off'}
        </button>
        {arbMarkers && !hestonOn && (
          <button className={`btn ${arbOn ? 'accent' : ''}`} onClick={() => setArbOn((v) => !v)}>
            Arbitrage flags {arbOn ? 'on' : 'off'}
          </button>
        )}
        {sviOn && (
          <span className="dim" style={{ fontSize: 12 }}>
            {sviGrid ? `Fitted ${fittedCount} of ${totalSlices} slices${fittedCount < totalSlices ? ' (sparse slices hidden)' : ''}` : 'SVI fit unavailable for this chain'}
          </span>
        )}
        {hestonOn && (
          <span className="dim" style={{ fontSize: 12 }}>
            {hestonQuery.isLoading ? 'Calibrating Heston to the chain…'
              : calib?.ok ? `Heston fit ${((calib.iv_rmse ?? 0) * 100).toFixed(1)} vol points across ${calib.n_instruments} options`
              : 'Heston calibration unavailable'}
          </span>
        )}
      </div>
      <Plot key={themeKey + (showSvi ? '-svi' : '') + (showHeston ? '-heston' : '')} data={traces} layout={layout} config={plotConfig}
        style={{ width: '100%', height: 580 }} useResizeHandler />
      <div className="chart-note">
        {showHeston
          ? 'Heston stochastic-vol surface, one process fit to the whole chain, with the raw market IV points scattered on top. It spans the calibrated maturities out to roughly a year, so the tenor axis reaches further than the raw and SVI views.'
          : showSvi
          ? 'SVI-fitted surface (continuous mesh) with the raw market IV points scattered on top. A point sitting off the mesh flags a data problem or a genuine dislocation; slices that fail to calibrate are hidden.'
          : 'Raw IV across strike and expiration (near-money band), interpolated to a grid with contour lines. Toggle a fitted overlay above. Drag to rotate, scroll to zoom.'}
        {showArb ? ' Red × marks flag arbitrage violations on the raw surface (see report below).' : ''}
      </div>
    </div>
    {hestonOn && <HestonPanel calib={calib} loading={hestonQuery.isLoading} />}
    {hasTerm && (
      <div className="chart-card" style={{ marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 13 }}>ATM term structure</strong>
          <span className="dim" style={{ fontSize: 12 }}>
            {useSviLine ? 'ATM vol read from the SVI fit at each expiration' : 'ATM vol interpolated at the forward for each expiration'}
          </span>
        </div>
        <Plot key={themeKey + '-term' + (useSviLine ? '-svi' : '')} data={termData} layout={termLayout} config={plotConfig}
          style={{ width: '100%', height: 300 }} useResizeHandler />
        {data.term_structure.read && (
          <div className="verdict" style={{ marginTop: 8, marginBottom: 4 }}>
            <b>{data.term_structure.read.headline}.</b> {data.term_structure.read.detail}
          </div>
        )}
        <div className="chart-note">
          ATM implied vol by maturity. An upward slope prices more uncertainty further out; an inverted, downward slope signals near-term stress.
          {sviOn && !hasSviAtm ? ' No slices calibrated, so this shows raw ATM.' : ''}
        </div>
      </div>
    )}
    <div className="chart-card" style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 13 }}>Arbitrage report</strong>
        <span className="dim" style={{ fontSize: 12 }}>
          {arbTotal
            ? `${arb.counts.butterfly} butterfly, ${arb.counts.calendar} calendar on the raw surface`
            : 'No calendar or butterfly violations on the raw surface'}
        </span>
      </div>
      {arb.truncated && (
        <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>Showing the 20 largest butterfly violations.</div>
      )}
      {violations.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 8, maxHeight: 320, minHeight: 0 }}>
          <table className="chain">
            <thead>
              <tr>
                <th className="l">Type</th>
                <th className="l">Expiration</th>
                <th>Location</th>
                <th className="l">Description</th>
              </tr>
            </thead>
            <tbody>
              {violations.map((v, i) => (
                <tr key={`${v.type}-${v.expiration}-${v.strike ?? v.moneyness}-${i}`}>
                  <td style={{ textAlign: 'left', fontWeight: 700, textTransform: 'capitalize', color: v.type === 'butterfly' ? cssVar('--accent') : cssVar('--neg') }}>{v.type}</td>
                  <td style={{ textAlign: 'left' }}>{v.expiration}</td>
                  <td>{v.strike != null ? v.strike.toFixed(0) : v.moneyness != null ? `${v.moneyness >= 0 ? '+' : ''}${(v.moneyness * 100).toFixed(0)}%` : '—'}</td>
                  <td style={{ textAlign: 'left', whiteSpace: 'normal', fontFamily: 'inherit', color: cssVar('--text-dim'), minWidth: 280 }}>{v.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="chart-note" style={{ marginTop: 8 }}>
        Calendar checks that total implied variance rises with maturity at fixed moneyness; butterfly checks that call prices stay convex in strike. Both run on the raw chain, so most flags are stale or crossed quotes rather than tradeable edges.
      </div>
    </div>
    </>
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

      <div className="verdict" style={{ marginBottom: 12 }}>
        {data.read ? (
          <>
            <b className={data.read.lean === 'rich' ? 'rich' : data.read.lean === 'cheap' ? 'cheap' : ''}>{data.read.headline}.</b>{' '}
            {data.read.detail}{' '}
            <span className="dim">{data.read.assumption}</span>
          </>
        ) : verdict}
      </div>
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
