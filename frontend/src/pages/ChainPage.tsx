import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useStore } from '../store'
import { api, type Contract } from '../api'
import { money, pct, int, greek, signClass, timeAgo, DASH } from '../format'

type Tab = 'calls' | 'puts' | 'combined'

export default function ChainPage() {
  const { ticker, ivSource, selectedContract, setSelectedContract } = useStore()
  const [numExpirations] = useState(6)
  const [expiration, setExpiration] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('combined')

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['chain', ticker, ivSource, numExpirations],
    queryFn: () => api.chain(ticker, ivSource, numExpirations),
  })

  // Default the selected expiration to the nearest one whenever the set changes.
  useEffect(() => {
    if (data && (!expiration || !data.expirations.includes(expiration))) {
      setExpiration(data.expirations[0] ?? null)
    }
  }, [data, expiration])

  const spot = data?.spot ?? null

  const forExp = useMemo(
    () => (data?.contracts ?? []).filter((c) => c.expiration === expiration),
    [data, expiration],
  )
  const calls = useMemo(
    () => forExp.filter((c) => c.type === 'call').sort((a, b) => a.strike - b.strike),
    [forExp],
  )
  const puts = useMemo(
    () => forExp.filter((c) => c.type === 'put').sort((a, b) => a.strike - b.strike),
    [forExp],
  )
  const strikes = useMemo(() => {
    const byStrike = new Map<number, { call?: Contract; put?: Contract }>()
    for (const c of calls) byStrike.set(c.strike, { ...(byStrike.get(c.strike) ?? {}), call: c })
    for (const p of puts) byStrike.set(p.strike, { ...(byStrike.get(p.strike) ?? {}), put: p })
    return [...byStrike.entries()].sort((a, b) => a[0] - b[0])
  }, [calls, puts])

  const atmStrike = useMemo(() => {
    if (spot === null || forExp.length === 0) return null
    return forExp.reduce(
      (best, c) => (Math.abs(c.strike - spot) < Math.abs(best - spot) ? c.strike : best),
      forExp[0].strike,
    )
  }, [forExp, spot])

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title">
          <span className="tk">{ticker}</span> Options Chain
        </div>
        <div className="stat">
          <span className="lbl">Spot</span>
          <span className="val">{money(spot)}</span>
        </div>
        {data?.iv_rank && (
          <div className="stat rank">
            <span className="lbl">IV Rank · {data.iv_rank.proxy === 'realized_vol' ? 'RV proxy' : data.iv_rank.proxy}</span>
            <span className="val">
              {data.iv_rank.rank.toFixed(0)}
              <span className="dim" style={{ fontSize: 12 }}> / {data.iv_rank.percentile.toFixed(0)}p</span>
            </span>
            <div className="bar"><i style={{ width: `${Math.max(2, Math.min(100, data.iv_rank.rank))}%` }} /></div>
          </div>
        )}
        {data && (
          <>
            <div className="stat">
              <span className="lbl">Div yield · {data.dividend.source}</span>
              <span className="val">{pct(data.dividend.value, 2)}</span>
            </div>
            <div className="stat">
              <span className="lbl">Rate · {data.rate.source}</span>
              <span className="val">{data.rate.as_of ?? DASH}</span>
            </div>
            <div className="stat">
              <span className="lbl">Data as of</span>
              <span className="val" style={{ fontSize: 13 }}>{timeAgo(data.as_of)}</span>
            </div>
          </>
        )}
      </div>

      {isLoading && <div className="msg"><span className="spin" />Loading live chain for {ticker}…</div>}
      {isError && <div className="msg err">Failed to load: {(error as Error).message}</div>}

      {data && (
        <>
          <div className="exps">
            {data.expirations.map((e) => (
              <button key={e} className={e === expiration ? 'active' : ''} onClick={() => setExpiration(e)}>
                {e}
              </button>
            ))}
          </div>

          <div className="tabs">
            {(['calls', 'puts', 'combined'] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          <div className="table-wrap">
            {tab === 'combined' ? (
              <CombinedTable
                strikes={strikes}
                spot={spot}
                atmStrike={atmStrike}
                selected={selectedContract}
                onSelect={setSelectedContract}
              />
            ) : (
              <SingleTable
                rows={tab === 'calls' ? calls : puts}
                type={tab === 'calls' ? 'call' : 'put'}
                spot={spot}
                atmStrike={atmStrike}
                selected={selectedContract}
                onSelect={setSelectedContract}
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}

function isItm(type: 'call' | 'put', strike: number, spot: number | null): boolean {
  if (spot === null) return false
  return type === 'call' ? strike < spot : strike > spot
}

function SingleTable({
  rows, type, spot, atmStrike, selected, onSelect,
}: {
  rows: Contract[]; type: 'call' | 'put'; spot: number | null; atmStrike: number | null
  selected: string | null; onSelect: (s: string) => void
}) {
  const atmRef = useRef<HTMLTableRowElement>(null)
  useEffect(() => {
    atmRef.current?.scrollIntoView({ block: 'center' })
  }, [atmStrike, rows.length])
  return (
    <table className="chain">
      <thead>
        <tr>
          <th className="center">Strike</th>
          <th>Bid</th><th>Ask</th><th>Mid</th>
          <th>Vol</th><th>OI</th><th>IV</th>
          <th>Δ</th><th>Γ</th><th>Vega</th><th>Θ/day</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => {
          const itm = isItm(type, c.strike, spot)
          return (
            <tr
              key={c.symbol}
              ref={c.strike === atmStrike ? atmRef : undefined}
              className={c.symbol === selected ? 'selected' : ''}
              onClick={() => onSelect(c.symbol)}
            >
              <td className={`strike ${itm ? 'itm' : ''}`}>{money(c.strike)}</td>
              <td>{money(c.bid)}</td>
              <td>{money(c.ask)}</td>
              <td>{money(c.mid)}</td>
              <td className="muted">{int(c.volume)}</td>
              <td className="muted">{int(c.open_interest)}</td>
              <td>{pct(c.iv)}</td>
              <td className={signClass(c.greeks.delta)}>{greek(c.greeks.delta)}</td>
              <td className="dim">{greek(c.greeks.gamma, 4)}</td>
              <td className="dim">{greek(c.greeks.vega)}</td>
              <td className={signClass(c.greeks.theta)}>{greek(c.greeks.theta)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function CombinedTable({
  strikes, spot, atmStrike, selected, onSelect,
}: {
  strikes: [number, { call?: Contract; put?: Contract }][]
  spot: number | null; atmStrike: number | null
  selected: string | null; onSelect: (s: string) => void
}) {
  const atmRef = useRef<HTMLTableRowElement>(null)
  useEffect(() => {
    atmRef.current?.scrollIntoView({ block: 'center' })
  }, [atmStrike, strikes.length])
  return (
    <table className="chain">
      <thead>
        <tr>
          <th>Vol</th><th>OI</th><th>IV</th><th>Δ</th><th>Bid</th><th>Ask</th>
          <th className="center">Strike</th>
          <th>Bid</th><th>Ask</th><th>Δ</th><th>IV</th><th>OI</th><th>Vol</th>
        </tr>
      </thead>
      <tbody>
        {strikes.map(([strike, { call, put }]) => {
          const callItm = isItm('call', strike, spot)
          const putItm = isItm('put', strike, spot)
          const sel = (call && call.symbol === selected) || (put && put.symbol === selected)
          return (
            <tr key={strike} ref={strike === atmStrike ? atmRef : undefined} className={sel ? 'selected' : ''}>
              <td className={`muted ${callItm ? 'itm' : ''}`} onClick={() => call && onSelect(call.symbol)}>{int(call?.volume)}</td>
              <td className={`muted ${callItm ? 'itm' : ''}`} onClick={() => call && onSelect(call.symbol)}>{int(call?.open_interest)}</td>
              <td className={callItm ? 'itm' : ''} onClick={() => call && onSelect(call.symbol)}>{pct(call?.iv)}</td>
              <td className={`${signClass(call?.greeks.delta)} ${callItm ? 'itm' : ''}`} onClick={() => call && onSelect(call.symbol)}>{greek(call?.greeks.delta)}</td>
              <td className={callItm ? 'itm' : ''} onClick={() => call && onSelect(call.symbol)}>{money(call?.bid)}</td>
              <td className={callItm ? 'itm' : ''} onClick={() => call && onSelect(call.symbol)}>{money(call?.ask)}</td>
              <td className="strike">{money(strike)}</td>
              <td className={putItm ? 'itm' : ''} onClick={() => put && onSelect(put.symbol)}>{money(put?.bid)}</td>
              <td className={putItm ? 'itm' : ''} onClick={() => put && onSelect(put.symbol)}>{money(put?.ask)}</td>
              <td className={`${signClass(put?.greeks.delta)} ${putItm ? 'itm' : ''}`} onClick={() => put && onSelect(put.symbol)}>{greek(put?.greeks.delta)}</td>
              <td className={putItm ? 'itm' : ''} onClick={() => put && onSelect(put.symbol)}>{pct(put?.iv)}</td>
              <td className={`muted ${putItm ? 'itm' : ''}`} onClick={() => put && onSelect(put.symbol)}>{int(put?.open_interest)}</td>
              <td className={`muted ${putItm ? 'itm' : ''}`} onClick={() => put && onSelect(put.symbol)}>{int(put?.volume)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
