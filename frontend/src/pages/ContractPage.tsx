import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api, type ContractDetail } from '../api'
import { money, pct, greek, timeAgo } from '../format'
import { baseLayout, plotColors, plotConfig, cssVar } from '../plotTheme'

type Tab = 'pricing' | 'probability'

export default function ContractPage() {
  const { ticker, ivSource, selectedContract } = useStore()
  const [tab, setTab] = useState<Tab>('pricing')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['contract', ticker, selectedContract, ivSource],
    queryFn: () => api.contract(ticker, selectedContract!, ivSource),
    enabled: !!selectedContract,
  })

  if (!selectedContract) {
    return (
      <div className="page">
        <div className="placeholder">
          <div className="mark" />
          <div className="big">No contract selected</div>
          <div>Choose a strike on the <Link to="/chain" style={{ color: 'var(--accent)' }}>Chain</Link> page to price it here.</div>
        </div>
      </div>
    )
  }

  const dte = data?.time_to_expiry != null ? Math.round(data.time_to_expiry * 365) : null

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title">
          <span className="tk">{ticker}</span>{' '}
          {data ? `${data.strike} ${data.type === 'call' ? 'Call' : 'Put'}` : selectedContract}
        </div>
        {data && (
          <>
            <div className="stat"><span className="lbl">Spot</span><span className="val">{money(data.spot)}</span></div>
            <div className="stat"><span className="lbl">Implied vol · {data.market_data.iv_source ?? '—'}</span><span className="val">{pct(data.iv)}</span></div>
            <div className="stat"><span className="lbl">Days to expiry</span><span className="val">{dte ?? '—'}</span></div>
            <div className="stat"><span className="lbl">Market mid</span><span className="val">{money(data.market_data.mid)}</span></div>
            <div className="stat"><span className="lbl">Data as of</span><span className="val" style={{ fontSize: 13 }}>{timeAgo(data.as_of)}</span></div>
          </>
        )}
      </div>

      <div className="tabs">
        <button className={tab === 'pricing' ? 'active' : ''} onClick={() => setTab('pricing')}>Pricing Models</button>
        <button className={tab === 'probability' ? 'active' : ''} onClick={() => setTab('probability')}>Probability &amp; Breakeven</button>
      </div>

      {isLoading && <div className="msg"><span className="spin" />Pricing {selectedContract}…</div>}
      {isError && <div className="msg err">Failed to load: {(error as Error).message}</div>}
      {data && tab === 'pricing' && <PricingTab d={data} dte={dte} />}
      {data && tab === 'probability' && <ProbabilityTab d={data} />}
    </div>
  )
}

function PricingTab({ d, dte }: { d: ContractDetail; dte: number | null }) {
  const bs = d.pricing.black_scholes
  const binom = d.pricing.binomial_american
  const eep = d.pricing.early_exercise_premium
  const g = d.greeks

  return (
    <div>
      <div className="cards">
        <div className="card">
          <div className="lbl">Black-Scholes</div>
          <div className="big">{money(bs)}</div>
          <div className="sub">European, closed form</div>
        </div>
        <div className="card">
          <div className="lbl">Binomial (American)</div>
          <div className="big">{money(binom)}</div>
          <div className="sub">CRR tree, 200 steps</div>
        </div>
        <div className={`card ${eep != null && eep > 0.005 ? 'hl' : ''}`}>
          <div className="lbl">Early-exercise premium</div>
          <div className="big">{money(eep)}</div>
          <div className="sub">Binomial minus Black-Scholes</div>
        </div>
        <div className="card">
          <div className="lbl">Market mid</div>
          <div className="big">{money(d.market_data.mid)}</div>
          <div className="sub">bid {money(d.market_data.bid)} / ask {money(d.market_data.ask)}</div>
        </div>
      </div>

      {d.read?.pricing && (
        <div className="verdict" style={{ marginBottom: 12 }}>
          <b>{d.read.pricing.headline}.</b> {d.read.pricing.detail}
        </div>
      )}

      <div className="note">
        Black-Scholes prices a European option in closed form. The binomial tree prices the American
        option, which can be exercised early, so the difference is the early-exercise premium. It is
        near zero for a call on a low-yield underlying and positive for puts and dividend-paying names.
      </div>

      <div className="section-h">Model inputs</div>
      <div className="kv-grid">
        <div className="kv2"><span className="lbl">Spot (S)</span><span className="v">{money(d.spot)}</span></div>
        <div className="kv2"><span className="lbl">Strike (K)</span><span className="v">{money(d.strike)}</span></div>
        <div className="kv2"><span className="lbl">Time (T)</span><span className="v">{dte ?? '—'}d · {d.time_to_expiry != null ? d.time_to_expiry.toFixed(3) : '—'}y</span></div>
        <div className="kv2"><span className="lbl">Rate (r)</span><span className="v">{pct(d.rate_used, 2)}</span></div>
        <div className="kv2"><span className="lbl">Implied vol (σ)</span><span className="v">{pct(d.iv)}</span></div>
        <div className="kv2"><span className="lbl">Dividend (q)</span><span className="v">{pct(d.dividend_yield, 2)}</span></div>
      </div>

      <div className="section-h">Greeks (Black-Scholes analytical)</div>
      <div className="kv-grid">
        <div className="kv2"><span className="lbl gk">Δ (delta)</span><span className="v">{greek(g.delta)}</span></div>
        <div className="kv2"><span className="lbl gk">Γ (gamma)</span><span className="v">{greek(g.gamma, 4)}</span></div>
        <div className="kv2"><span className="lbl gk">ν (vega) · per 1%</span><span className="v">{greek(g.vega)}</span></div>
        <div className="kv2"><span className="lbl gk">θ (theta) · per day</span><span className="v">{greek(g.theta)}</span></div>
        <div className="kv2"><span className="lbl gk">ρ (rho) · per 1%</span><span className="v">{greek(g.rho)}</span></div>
      </div>
    </div>
  )
}

function ProbabilityTab({ d }: { d: ContractDetail }) {
  const c = plotColors()
  const p = d.probability
  const S = d.spot, K = d.strike, T = d.time_to_expiry, r = d.rate_used, sigma = d.iv
  const q = d.dividend_yield ?? 0
  const be = p.breakeven

  const chart = (() => {
    if (S == null || T == null || r == null || !sigma || T <= 0) return null
    const m = Math.log(S) + (r - q - 0.5 * sigma * sigma) * T
    const sd = sigma * Math.sqrt(T)
    const lo = S * Math.exp(-4 * sd), hi = S * Math.exp(4 * sd)
    const n = 240
    const xs: number[] = [], ys: number[] = []
    for (let i = 0; i < n; i++) {
      const x = lo + ((hi - lo) * i) / (n - 1)
      const z = (Math.log(x) - m) / sd
      xs.push(x)
      ys.push(x <= 0 ? 0 : Math.exp(-0.5 * z * z) / (x * sd * Math.sqrt(2 * Math.PI)))
    }
    // Shade the profitable region beyond the breakeven.
    const profit = xs.map((x, i) => {
      if (be == null) return null
      return (d.type === 'call' ? x >= be : x <= be) ? ys[i] : null
    })
    const line = (x: number, color: string, dash: string) =>
      ({ type: 'line', x0: x, x1: x, y0: 0, y1: 1, yref: 'paper', line: { color, dash, width: 1 } })
    const lbl = (x: number, text: string, color: string, anchor: string) =>
      ({ x, y: 1, yref: 'paper', text, showarrow: false, font: { color, size: 10 }, yanchor: 'bottom', xanchor: anchor })

    const data = [
      { type: 'scatter', mode: 'lines', name: 'Profit region', x: xs, y: profit,
        line: { width: 0 }, fill: 'tozeroy', fillcolor: cssVar('--accent-soft'), hoverinfo: 'skip' },
      { type: 'scatter', mode: 'lines', name: 'Terminal density', x: xs, y: ys,
        line: { color: c.accent, width: 2 }, hovertemplate: 'S_T %{x:.0f}<extra></extra>' },
    ]
    const layout = {
      ...baseLayout(), height: 380, margin: { l: 20, r: 18, t: 24, b: 44 },
      xaxis: { ...baseLayout().xaxis, title: { text: 'Underlying at expiry' } },
      yaxis: { ...baseLayout().yaxis, showticklabels: false, title: { text: 'Probability density' }, rangemode: 'tozero' },
      shapes: [
        S != null ? line(S, c.muted, 'dot') : null,
        line(K, c.text, 'dash'),
        be != null ? line(be, c.accent, 'solid') : null,
      ].filter(Boolean),
      annotations: [
        S != null ? lbl(S, 'Spot', c.muted, 'right') : null,
        lbl(K, 'Strike', c.text, 'left'),
        be != null ? lbl(be, 'Breakeven', c.accent, 'left') : null,
      ].filter(Boolean),
    }
    return { data, layout }
  })()

  return (
    <div>
      <div className="cards">
        <div className="card">
          <div className="lbl">Prob. in the money</div>
          <div className="big">{pct(p.prob_itm, 1)}</div>
          <div className="sub">risk-neutral N(d₂)</div>
        </div>
        <div className="card hl">
          <div className="lbl">Prob. of profit</div>
          <div className="big">{pct(p.prob_of_profit, 1)}</div>
          <div className="sub">long at the market mid</div>
        </div>
        <div className="card">
          <div className="lbl">Breakeven</div>
          <div className="big">{money(be)}</div>
          <div className="sub">{d.type === 'call' ? 'strike + premium' : 'strike − premium'}</div>
        </div>
      </div>

      {d.read?.probability && (
        <div className="verdict" style={{ marginBottom: 12 }}>
          <b>{d.read.probability.headline}.</b> {d.read.probability.detail}
        </div>
      )}

      <div className="note">
        Probabilities use the option's own implied volatility under the lognormal (Black-Scholes)
        model, so they are forward-looking and risk-neutral, not real-world odds. Probability in the
        money is the chance of finishing past the strike; probability of profit is the chance of
        finishing past the breakeven, where the premium is recovered.
      </div>

      {chart ? (
        <div className="chart-card">
          <Plot data={chart.data} layout={chart.layout} config={plotConfig}
            style={{ width: '100%', height: 380 }} useResizeHandler />
          <div className="chart-note">
            Risk-neutral distribution of the underlying at expiry. The shaded area is the profitable region beyond the breakeven.
          </div>
        </div>
      ) : (
        <div className="chart-card"><div className="msg">Distribution unavailable (needs a live IV and time to expiry).</div></div>
      )}
    </div>
  )
}
