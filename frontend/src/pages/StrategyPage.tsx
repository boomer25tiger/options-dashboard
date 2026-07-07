import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api, type StrategyLegInput, type StrategyResponse } from '../api'
import { money, greek } from '../format'
import { baseLayout, plotColors, plotConfig, cssVar } from '../plotTheme'

type Side = 'buy' | 'sell'
type OptType = 'call' | 'put' | 'stock'
interface Leg { id: number; side: Side; quantity: number; type: OptType; strike: number | null; expiration: string | null }

let LEG_ID = 1
const newLeg = (partial: Partial<Leg> = {}): Leg =>
  ({ id: LEG_ID++, side: 'buy', quantity: 1, type: 'call', strike: null, expiration: null, ...partial })

function nearestStrike(strikes: number[], target: number): number | null {
  if (!strikes.length) return null
  return strikes.reduce((b, s) => (Math.abs(s - target) < Math.abs(b - target) ? s : b), strikes[0])
}

function legLabel(r: StrategyResponse['legs'][number]): string {
  const q = (r.quantity > 0 ? '+' : '') + r.quantity
  if (r.option_type === 'stock') return `${q} Stock`
  const t = r.option_type[0].toUpperCase() + r.option_type.slice(1)
  return `${q} ${t} ${r.strike}`
}

const PRESET_GROUPS = ['Directional', 'Neutral / income', 'Hedged']
const PRESETS = [
  { key: 'bull_call', nm: 'Bull call spread', ds: 'Long ATM call, short a higher call', group: 'Directional' },
  { key: 'bear_put', nm: 'Bear put spread', ds: 'Long ATM put, short a lower put', group: 'Directional' },
  { key: 'bull_put', nm: 'Bull put spread', ds: 'Short a higher put, long a lower put (credit)', group: 'Directional' },
  { key: 'bear_call', nm: 'Bear call spread', ds: 'Short a lower call, long a higher call (credit)', group: 'Directional' },
  { key: 'straddle', nm: 'Long straddle', ds: 'Long the ATM call and put', group: 'Neutral / income' },
  { key: 'strangle', nm: 'Long strangle', ds: 'Long an OTM call and OTM put', group: 'Neutral / income' },
  { key: 'iron_condor', nm: 'Iron condor', ds: 'Short strangle inside long wings', group: 'Neutral / income' },
  { key: 'butterfly', nm: 'Long call butterfly', ds: 'Pinned to the middle strike', group: 'Neutral / income' },
  { key: 'covered_call', nm: 'Covered call', ds: 'Long 100 shares, short an OTM call', group: 'Hedged' },
  { key: 'protective_put', nm: 'Protective put', ds: 'Long 100 shares, long an OTM put', group: 'Hedged' },
  { key: 'collar', nm: 'Collar', ds: 'Shares, long a put, short a call', group: 'Hedged' },
]

function buildPreset(key: string, exp: string, strikes: number[], spot: number): Leg[] {
  const w = Math.max(1, Math.round(spot * 0.01))
  const w2 = Math.max(2, Math.round(spot * 0.02))
  const K = (t: number) => nearestStrike(strikes, t)
  const call = (side: Side, k: number | null) => newLeg({ side, type: 'call', strike: k, expiration: exp })
  const put = (side: Side, k: number | null) => newLeg({ side, type: 'put', strike: k, expiration: exp })
  const stock = (qty: number) => newLeg({ side: 'buy', type: 'stock', quantity: qty, strike: null, expiration: null })
  const atm = K(spot)
  switch (key) {
    case 'bull_call': return [call('buy', atm), call('sell', K(spot + w))]
    case 'bear_put': return [put('buy', atm), put('sell', K(spot - w))]
    case 'bull_put': return [put('sell', K(spot - w)), put('buy', K(spot - w2))]
    case 'bear_call': return [call('sell', K(spot + w)), call('buy', K(spot + w2))]
    case 'straddle': return [call('buy', atm), put('buy', atm)]
    case 'strangle': return [call('buy', K(spot + w)), put('buy', K(spot - w))]
    case 'iron_condor': return [put('sell', K(spot - w)), put('buy', K(spot - w2)), call('sell', K(spot + w)), call('buy', K(spot + w2))]
    case 'butterfly': return [call('buy', K(spot - w)), newLeg({ side: 'sell', type: 'call', strike: atm, expiration: exp, quantity: 2 }), call('buy', K(spot + w))]
    case 'covered_call': return [stock(100), call('sell', K(spot + w))]
    case 'protective_put': return [stock(100), put('buy', K(spot - w))]
    case 'collar': return [stock(100), put('buy', K(spot - w)), call('sell', K(spot + w))]
    default: return []
  }
}

export default function StrategyPage() {
  const { ticker, ivSource } = useStore()
  const [tab, setTab] = useState<'freeform' | 'presets'>('presets')
  const [legs, setLegs] = useState<Leg[]>([])
  const [presetExp, setPresetExp] = useState<string | null>(null)

  const chain = useQuery({ queryKey: ['chain', ticker, ivSource, 8], queryFn: () => api.chain(ticker, ivSource, 8) })
  const spot = chain.data?.spot ?? 0
  const expirations = chain.data?.expirations ?? []
  const strikesByExp = useMemo(() => {
    const map: Record<string, number[]> = {}
    for (const cnt of chain.data?.contracts ?? []) {
      (map[cnt.expiration] ??= []).push(cnt.strike)
    }
    for (const k of Object.keys(map)) map[k] = [...new Set(map[k])].sort((a, b) => a - b)
    return map
  }, [chain.data])

  if (presetExp === null && expirations.length) {
    setPresetExp(expirations.find((e) => (Date.parse(e) - Date.now()) / 86400000 >= 7) ?? expirations[0])
  }

  const apiLegs: StrategyLegInput[] = legs
    .filter((l) => l.quantity > 0 && (l.type === 'stock' || (l.strike != null && l.expiration)))
    .map((l) => ({
      option_type: l.type,
      quantity: l.side === 'buy' ? l.quantity : -l.quantity,
      strike: l.type === 'stock' ? null : l.strike,
      expiration: l.type === 'stock' ? null : l.expiration,
    }))

  const price = useQuery({
    queryKey: ['strategy', ticker, ivSource, JSON.stringify(apiLegs)],
    queryFn: () => api.strategyPrice(ticker, apiLegs, ivSource),
    enabled: apiLegs.length > 0,
  })

  const update = (id: number, patch: Partial<Leg>) =>
    setLegs((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)))
  const remove = (id: number) => setLegs((ls) => ls.filter((l) => l.id !== id))
  const addLeg = () => {
    const exp = expirations[0] ?? null
    const strike = exp ? nearestStrike(strikesByExp[exp] ?? [], spot) : null
    setLegs((ls) => [...ls, newLeg({ expiration: exp, strike })])
  }
  const applyPreset = (key: string) => {
    if (!presetExp || !spot) return
    setLegs(buildPreset(key, presetExp, strikesByExp[presetExp] ?? [], spot))
    setTab('freeform')
  }

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title"><span className="tk">{ticker}</span> Strategy Builder</div>
        <div className="stat"><span className="lbl">Spot</span><span className="val">{money(chain.data?.spot ?? null)}</span></div>
      </div>

      <div className="tabs">
        <button className={tab === 'freeform' ? 'active' : ''} onClick={() => setTab('freeform')}>Freeform</button>
        <button className={tab === 'presets' ? 'active' : ''} onClick={() => setTab('presets')}>Presets</button>
      </div>

      {tab === 'presets' && (
        <div>
          <div className="builder-controls">
            <span className="dim" style={{ fontSize: 12 }}>Expiration</span>
            <select className="field" value={presetExp ?? ''} onChange={(e) => setPresetExp(e.target.value)}>
              {expirations.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
            </select>
          </div>
          {PRESET_GROUPS.map((grp) => (
            <div key={grp}>
              <div className="preset-group">{grp}</div>
              <div className="preset-grid">
                {PRESETS.filter((p) => p.group === grp).map((p) => (
                  <button className="preset-btn" key={p.key} onClick={() => applyPreset(p.key)}>
                    <div className="nm">{p.nm}</div>
                    <div className="ds">{p.ds}</div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'freeform' && (
        <div>
          <div className="legs">
            {legs.length === 0 && <div className="leg-row"><span className="dim">No legs yet. Add one below, or start from a preset.</span></div>}
            {legs.map((leg) => (
              <div className="leg-row" key={leg.id}>
                <div className="side">
                  <button className={`buy ${leg.side === 'buy' ? 'on' : ''}`} onClick={() => update(leg.id, { side: 'buy' })}>Buy</button>
                  <button className={`sell ${leg.side === 'sell' ? 'on' : ''}`} onClick={() => update(leg.id, { side: 'sell' })}>Sell</button>
                </div>
                <input className="field qty" type="number" min={1} value={leg.quantity}
                  onChange={(e) => update(leg.id, { quantity: Math.max(1, Number(e.target.value) || 1) })} />
                <select className="field" value={leg.type} onChange={(e) => update(leg.id, { type: e.target.value as OptType })}>
                  <option value="call">Call</option>
                  <option value="put">Put</option>
                  <option value="stock">Stock</option>
                </select>
                {leg.type !== 'stock' && (
                  <>
                    <select className="field" value={leg.expiration ?? ''}
                      onChange={(e) => update(leg.id, { expiration: e.target.value, strike: nearestStrike(strikesByExp[e.target.value] ?? [], spot) })}>
                      <option value="" disabled>expiry</option>
                      {expirations.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
                    </select>
                    <select className="field" value={leg.strike ?? ''} onChange={(e) => update(leg.id, { strike: Number(e.target.value) })}>
                      <option value="" disabled>strike</option>
                      {(strikesByExp[leg.expiration ?? ''] ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </>
                )}
                <button className="x-btn" onClick={() => remove(leg.id)} title="Remove leg">×</button>
              </div>
            ))}
          </div>
          <button className="btn accent" onClick={addLeg}>+ Add leg</button>
        </div>
      )}

      {apiLegs.length === 0 && <div className="note" style={{ marginTop: 16 }}>Build a position with the Presets or Freeform tab to see its metrics and payoff.</div>}
      {price.isLoading && <div className="msg"><span className="spin" />Pricing position…</div>}
      {price.isError && <div className="msg err">Failed to price: {(price.error as Error).message}</div>}
      {price.data && <StrategyResult data={price.data} />}
    </div>
  )
}

function StrategyResult({ data }: { data: StrategyResponse }) {
  const c = plotColors()
  const s = data.summary
  const debit = s.net_cost >= 0
  const g = s.greeks

  const xs = data.payoff.underlying
  const labels = Object.keys(data.payoff.curves)
  const expiryYs = data.payoff.curves['expiry'] ?? data.payoff.curves[labels[labels.length - 1]] ?? []
  const prof = expiryYs.map((y) => (y >= 0 ? y : null))
  const loss = expiryYs.map((y) => (y <= 0 ? y : null))

  const vline = (x: number, color: string, dash: string) =>
    ({ type: 'line', x0: x, x1: x, y0: 0, y1: 1, yref: 'paper', line: { color, dash, width: 1 } })

  const chartData = [
    { type: 'scatter', mode: 'lines', x: xs, y: prof, line: { width: 0 }, fill: 'tozeroy', fillcolor: cssVar('--pos-soft'), showlegend: false, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', x: xs, y: loss, line: { width: 0 }, fill: 'tozeroy', fillcolor: cssVar('--neg-soft'), showlegend: false, hoverinfo: 'skip' },
    ...labels.filter((l) => l !== 'expiry').map((l) => ({
      type: 'scatter', mode: 'lines', name: l === 'now' ? 'Now' : l, x: xs, y: data.payoff.curves[l],
      line: { color: c.muted, width: 1, dash: 'dot' }, hovertemplate: '%{y:.0f}<extra></extra>',
    })),
    { type: 'scatter', mode: 'lines', name: 'At expiry', x: xs, y: expiryYs, line: { color: c.accent, width: 2.5 }, hovertemplate: 'P&L %{y:.0f}<extra></extra>' },
  ]
  const layout = {
    ...baseLayout(), height: 420, showlegend: true,
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.1, yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    margin: { l: 62, r: 18, t: 30, b: 44 },
    xaxis: { ...baseLayout().xaxis, title: { text: 'Underlying at expiry' } },
    yaxis: { ...baseLayout().yaxis, title: { text: 'Profit / loss ($)' }, zeroline: true, zerolinecolor: c.border },
    shapes: [
      data.spot != null ? vline(data.spot, c.muted, 'dot') : null,
      ...s.breakevens.map((b) => vline(b, c.text, 'dash')),
    ].filter(Boolean),
    annotations: [
      data.spot != null ? { x: data.spot, y: 1, yref: 'paper', text: 'Spot', showarrow: false, font: { color: c.muted, size: 10 }, yanchor: 'bottom', xanchor: 'right' } : null,
    ].filter(Boolean),
  }

  return (
    <div style={{ marginTop: 4 }}>
      <div className="cards">
        <div className="card">
          <div className="lbl">Net {debit ? 'debit' : 'credit'}</div>
          <div className="big">{money(Math.abs(s.net_cost))}</div>
          <div className="sub">{debit ? 'you pay' : 'you receive'}</div>
        </div>
        <div className="card">
          <div className="lbl">Max profit</div>
          <div className="big">{s.max_profit == null ? 'Unlimited' : money(s.max_profit)}</div>
        </div>
        <div className="card">
          <div className="lbl">Max loss</div>
          <div className="big">{s.max_loss == null ? 'Unlimited' : money(s.max_loss)}</div>
        </div>
        <div className="card hl">
          <div className="lbl">Prob. of profit</div>
          <div className="big">{s.prob_of_profit == null ? '—' : (s.prob_of_profit * 100).toFixed(1) + '%'}</div>
          <div className="sub">lognormal, at ATM IV</div>
        </div>
      </div>

      {data.read && (
        <div className="verdict" style={{ marginTop: 12 }}>
          <b className={data.read.flag === 'risk' ? 'neg' : ''}>{data.read.headline}.</b>{' '}
          {data.read.detail}{' '}
          <span className="dim">{data.read.note}</span>
        </div>
      )}

      <div className="section-h">Breakevens &amp; net Greeks</div>
      <div className="kv-grid">
        <div className="kv2"><span className="lbl">Breakeven(s)</span><span className="v">{s.breakevens.length ? s.breakevens.map((b) => b.toFixed(2)).join(', ') : '—'}</span></div>
        <div className="kv2"><span className="lbl gk">Δ (delta)</span><span className="v">{greek(g.delta, 1)}</span></div>
        <div className="kv2"><span className="lbl gk">Γ (gamma)</span><span className="v">{greek(g.gamma, 3)}</span></div>
        <div className="kv2"><span className="lbl gk">ν (vega) · per 1%</span><span className="v">{greek(g.vega, 1)}</span></div>
        <div className="kv2"><span className="lbl gk">θ (theta) · per day</span><span className="v">{greek(g.theta, 1)}</span></div>
        <div className="kv2"><span className="lbl gk">ρ (rho) · per 1%</span><span className="v">{greek(g.rho, 1)}</span></div>
      </div>

      <div className="chart-card">
        <Plot data={chartData} layout={layout} config={plotConfig} style={{ width: '100%', height: 420 }} useResizeHandler />
        <div className="chart-note">
          Time-aware payoff: the bold line is P&amp;L at expiry, the dotted lines are P&amp;L at earlier dates priced through the engine. Green is profit, red is loss; dashed verticals are breakevens.
        </div>
      </div>

      <div className="section-h" style={{ marginTop: 16 }}>Per-leg breakdown</div>
      <div className="table-wrap" style={{ maxHeight: 'none', marginBottom: 8 }}>
        <table className="breakdown">
          <thead>
            <tr>
              <th className="l">Leg</th><th>Price</th><th>Cost</th>
              <th className="gk">Δ (delta)</th><th className="gk">Γ (gamma)</th>
              <th className="gk">ν (vega)</th><th className="gk">θ (theta)</th><th className="gk">ρ (rho)</th>
            </tr>
          </thead>
          <tbody>
            {data.legs.map((r, i) => (
              <tr key={i}>
                <td className="l">{legLabel(r)}</td>
                <td>{money(r.price)}</td>
                <td>{money(r.cost)}</td>
                <td>{greek(r.greeks.delta, 1)}</td>
                <td>{greek(r.greeks.gamma, 3)}</td>
                <td>{greek(r.greeks.vega, 1)}</td>
                <td>{greek(r.greeks.theta, 1)}</td>
                <td>{greek(r.greeks.rho, 1)}</td>
              </tr>
            ))}
            <tr className="total">
              <td className="l">Net position</td>
              <td></td>
              <td>{money(s.net_cost)}</td>
              <td>{greek(g.delta, 1)}</td>
              <td>{greek(g.gamma, 3)}</td>
              <td>{greek(g.vega, 1)}</td>
              <td>{greek(g.theta, 1)}</td>
              <td>{greek(g.rho, 1)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="note">
        Net cost and net Greeks are the signed sum of the legs above, shown in the totals row. Breakevens, max profit and loss, and probability of profit are not per-leg sums; they come from the shape of the combined payoff. For a vertical, for example, max profit is the strike width minus the net debit, and the breakeven is the long strike plus the net debit.
      </div>
    </div>
  )
}
