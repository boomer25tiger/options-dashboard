import { create } from 'zustand'

export type IvSource = 'auto' | 'alpaca' | 'yfinance'
export type Theme = 'dark' | 'light'

function applyTheme(t: Theme) {
  document.documentElement.setAttribute('data-theme', t)
}

const savedTheme: Theme =
  ((typeof localStorage !== 'undefined' && localStorage.getItem('theme')) as Theme) || 'dark'
applyTheme(savedTheme)

interface AppState {
  ticker: string
  ivSource: IvSource
  selectedContract: string | null
  dividendOverride: number | null
  theme: Theme
  setTicker: (t: string) => void
  setIvSource: (s: IvSource) => void
  setSelectedContract: (sym: string | null) => void
  setDividendOverride: (q: number | null) => void
  toggleTheme: () => void
}

// Shared state that persists across pages: the active underlying drives every
// page, the selected contract drives the Contract page, the IV source toggle
// applies everywhere, and the theme is remembered across sessions.
export const useStore = create<AppState>((set, get) => ({
  ticker: 'SPY',
  ivSource: 'auto',
  selectedContract: null,
  dividendOverride: null,
  theme: savedTheme,
  setTicker: (t) => set({ ticker: t.trim().toUpperCase(), selectedContract: null }),
  setIvSource: (ivSource) => set({ ivSource }),
  setSelectedContract: (selectedContract) => set({ selectedContract }),
  setDividendOverride: (dividendOverride) => set({ dividendOverride }),
  toggleTheme: () => {
    const theme: Theme = get().theme === 'dark' ? 'light' : 'dark'
    try { localStorage.setItem('theme', theme) } catch { /* ignore */ }
    applyTheme(theme)
    set({ theme })
  },
}))
