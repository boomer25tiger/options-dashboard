import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useStore, type IvSource } from '../store'
import { api } from '../api'
import { pct, timeAgo } from '../format'

const IV_SOURCES: IvSource[] = ['auto', 'alpaca', 'yfinance']

export default function TopBar() {
  const navigate = useNavigate()
  const { ticker, setTicker, ivSource, setIvSource, selectedContract, theme, toggleTheme } = useStore()
  const [draft, setDraft] = useState(ticker)
  const [showAssume, setShowAssume] = useState(false)

  useEffect(() => setDraft(ticker), [ticker])

  const market = useQuery({ queryKey: ['market'], queryFn: api.marketStatus, staleTime: 30_000 })
  const assume = useQuery({
    queryKey: ['assumptions', ticker],
    queryFn: () => api.assumptions(ticker),
    enabled: showAssume,
  })

  const isOpen = market.data?.is_open
  const dotClass = isOpen === true ? 'open' : isOpen === false ? 'closed' : ''

  return (
    <header className="topbar">
      <div className="brand">
        <span className="mark" />
        Options Desk <span className="sub">/ {ticker}</span>
      </div>

      <form
        className="ticker-box"
        onSubmit={(e) => {
          e.preventDefault()
          if (draft.trim()) setTicker(draft)
        }}
      >
        <label>Ticker</label>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck={false}
          aria-label="Ticker symbol"
        />
      </form>

      <div className="segmented" role="group" aria-label="IV source">
        {IV_SOURCES.map((s) => (
          <button
            key={s}
            className={ivSource === s ? 'active' : ''}
            onClick={() => setIvSource(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="spacer" />

      {selectedContract && (
        <button className="pill chip" onClick={() => navigate('/contract')} title="Go to Contract">
          {selectedContract}
        </button>
      )}

      <div className="status" title={market.data?.timestamp ?? ''}>
        <span className={`dot ${dotClass}`} />
        {isOpen === true ? <b>Market open</b> : isOpen === false ? <b>Market closed</b> : 'Status'}
        {market.data?.timestamp && <span className="dim">· {timeAgo(market.data.timestamp)}</span>}
      </div>

      <button className="pill icon-btn" onClick={toggleTheme} title="Toggle light / dark">
        {theme === 'dark' ? '☀' : '☾'}
      </button>

      <div className="popover-wrap">
        <button className="pill" onClick={() => setShowAssume((v) => !v)}>
          Assumptions
        </button>
        {showAssume && (
          <>
            <div
              style={{ position: 'fixed', inset: 0, zIndex: 30 }}
              onClick={() => setShowAssume(false)}
            />
            <div className="popover">
              <h4>Risk-free rate</h4>
              {assume.isLoading && <div className="kv"><span>loading…</span></div>}
              {assume.data && (
                <>
                  <div className="kv"><span>source</span><b>{assume.data.rate.source}</b></div>
                  <div className="kv"><span>as of</span><b>{assume.data.rate.as_of ?? '—'}</b></div>
                  {Object.entries(assume.data.rate.sample).map(([t, r]) => (
                    <div className="kv" key={t}><span>{t}y</span><b>{pct(r, 2)}</b></div>
                  ))}
                  <h4 style={{ marginTop: 12 }}>Dividend yield</h4>
                  <div className="kv">
                    <span>{assume.data.dividend.source}</span>
                    <b>{pct(assume.data.dividend.value, 2)}</b>
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </header>
  )
}
