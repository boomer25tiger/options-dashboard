import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Plot from '../Plot'
import { useStore } from '../store'
import { api } from '../api'
import { money, pct, timeAgo } from '../format'
import { baseLayout, plotColors, plotConfig } from '../plotTheme'

const METRICS = [
  { key: 'atm_iv', label: 'ATM implied vol', kind: 'pct' },
  { key: 'iv_rank', label: 'IV rank proxy', kind: 'rank' },
  { key: 'rv_20', label: 'Realized vol · 20d', kind: 'pct' },
  { key: 'rv_10', label: 'Realized vol · 10d', kind: 'pct' },
  { key: 'rv_30', label: 'Realized vol · 30d', kind: 'pct' },
  { key: 'rv_60', label: 'Realized vol · 60d', kind: 'pct' },
  { key: 'spot', label: 'Spot price', kind: 'price' },
]

function Loading({ label }: { label: string }) {
  return <div className="msg"><span className="spin" />{label}</div>
}

export default function HistoryPage() {
  const { ticker, ivSource } = useStore()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])
  const [metric, setMetric] = useState('atm_iv')

  const tickersQ = useQuery({ queryKey: ['history-tickers'], queryFn: api.historyTickers })
  const visitsQ = useQuery({ queryKey: ['history-visits'], queryFn: () => api.historyVisits(undefined, 300) })
  const allTickers = tickersQ.data?.tickers ?? []

  useEffect(() => {
    if (selected.length === 0 && allTickers.length) {
      setSelected(allTickers.includes(ticker) ? [ticker] : [allTickers[0]])
    }
  }, [allTickers, ticker, selected.length])

  const seriesQ = useQuery({
    queryKey: ['history-series', selected, metric],
    queryFn: () => api.historySeries(selected, metric),
    enabled: selected.length > 0,
  })

  const record = useMutation({
    mutationFn: () => api.historyRecord(ticker, ivSource),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['history-tickers'] })
      qc.invalidateQueries({ queryKey: ['history-visits'] })
      qc.invalidateQueries({ queryKey: ['history-series'] })
      setSelected((s) => (s.includes(ticker) ? s : [...s, ticker]))
    },
  })

  const toggle = (t: string) => setSelected((s) => (s.includes(t) ? s.filter((x) => x !== t) : [...s, t]))

  const visits = visitsQ.data?.visits ?? []
  const tableVisits = selected.length ? visits.filter((v) => selected.includes(v.ticker)) : visits
  const metricDef = METRICS.find((m) => m.key === metric)!

  const c = plotColors()
  const colors = [c.accent, '#5aa9e6', c.pos, c.neg, c.muted, '#b98adf']
  const series = seriesQ.data?.series ?? {}
  const chartData = Object.entries(series).map(([tk, pts], i) => ({
    type: 'scatter', mode: 'lines+markers', name: tk,
    x: pts.map((p) => p.timestamp),
    y: pts.map((p) => (p.value == null ? null : metricDef.kind === 'pct' ? p.value * 100 : p.value)),
    line: { width: 2, color: colors[i % colors.length] },
    marker: { size: 5, color: colors[i % colors.length] },
    hovertemplate: `${tk} %{y:.2f}<extra></extra>`,
  }))
  const hasPoints = chartData.some((d) => d.x.length > 0)
  const yTitle = metricDef.kind === 'pct' ? metricDef.label + ' %'
    : metricDef.kind === 'rank' ? metricDef.label + ' (0-100)' : metricDef.label
  const layout = {
    ...baseLayout(), height: 380, showlegend: true,
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.1, yanchor: 'bottom', bgcolor: 'rgba(0,0,0,0)', font: { color: c.muted, size: 11 } },
    margin: { l: 60, r: 18, t: 30, b: 44 },
    xaxis: { ...baseLayout().xaxis, type: 'date', title: { text: 'Visit time' } },
    yaxis: { ...baseLayout().yaxis, title: { text: yTitle } },
  }

  const empty = !visitsQ.isLoading && visits.length === 0

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title"><span className="tk">{ticker}</span> History</div>
        <div style={{ marginLeft: 'auto' }}>
          <button className="btn accent" disabled={record.isPending} onClick={() => record.mutate()}>
            {record.isPending ? 'Recording…' : `Record ${ticker} snapshot`}
          </button>
        </div>
      </div>

      {record.isError && <div className="msg err">Could not record: {(record.error as Error).message}</div>}

      {empty && (
        <div className="note">
          No history yet. Each snapshot records the key metrics for a ticker (spot, ATM IV, realized vol, and the rank proxy) with a timestamp. Record one now, and visits also accrue automatically as you open the Chain page for a ticker. Over time the stored ATM IV builds a real IV series, which seeds true IV rank.
        </div>
      )}

      {!empty && (
        <>
          <div className="builder-controls">
            <span className="dim" style={{ fontSize: 12 }}>Compare</span>
            {allTickers.map((t) => (
              <button key={t} className={`pill ${selected.includes(t) ? 'chip' : ''}`} onClick={() => toggle(t)}>{t}</button>
            ))}
            <span className="dim" style={{ fontSize: 12, marginLeft: 14 }}>Metric</span>
            <select className="field" value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </div>

          <div className="chart-card" style={{ marginBottom: 16 }}>
            {seriesQ.isLoading && <Loading label="Loading series…" />}
            {seriesQ.data && !hasPoints && <div className="msg">Only one point so far for the selected tickers. The line fills in as snapshots accumulate over time.</div>}
            {hasPoints && <Plot data={chartData} layout={layout} config={plotConfig} style={{ width: '100%', height: 380 }} useResizeHandler />}
            <div className="chart-note">{metricDef.label} over time. Toggle tickers above to overlay and compare across names.</div>
          </div>

          <div className="section-h">Recorded visits</div>
          <div className="table-wrap" style={{ maxHeight: 'none' }}>
            <table className="breakdown">
              <thead>
                <tr>
                  <th className="l">Ticker</th><th className="l">Time</th>
                  <th>Spot</th><th>ATM IV</th><th>RV 20d</th><th>IV rank</th>
                </tr>
              </thead>
              <tbody>
                {tableVisits.map((v) => (
                  <tr key={v.id}>
                    <td className="l">{v.ticker}</td>
                    <td className="l">{timeAgo(v.timestamp)}</td>
                    <td>{money(v.spot)}</td>
                    <td>{pct(v.atm_iv)}</td>
                    <td>{pct(v.rv_20)}</td>
                    <td>{v.iv_rank == null ? '—' : v.iv_rank.toFixed(0)}</td>
                  </tr>
                ))}
                {tableVisits.length === 0 && (
                  <tr><td className="l" colSpan={6}><span className="dim">No visits for the selected tickers.</span></td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
