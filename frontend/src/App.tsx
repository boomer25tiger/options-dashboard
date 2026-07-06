import { Routes, Route, Navigate, NavLink } from 'react-router-dom'
import TopBar from './components/TopBar'
import ChainPage from './pages/ChainPage'
import AnalysisPage from './pages/AnalysisPage'
import ContractPage from './pages/ContractPage'
import StrategyPage from './pages/StrategyPage'
import HistoryPage from './pages/HistoryPage'

const PAGES = [
  { to: '/chain', label: 'Chain' },
  { to: '/analysis', label: 'Analysis' },
  { to: '/strategy', label: 'Strategy' },
  { to: '/contract', label: 'Contract' },
  { to: '/history', label: 'History' },
]

export default function App() {
  return (
    <div className="app">
      <TopBar />
      <nav className="nav">
        {PAGES.map((p) => (
          <NavLink key={p.to} to={p.to} className={({ isActive }) => (isActive ? 'active' : '')}>
            {p.label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route path="/" element={<Navigate to="/chain" replace />} />
        <Route path="/chain" element={<ChainPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/strategy" element={<StrategyPage />} />
        <Route path="/contract" element={<ContractPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Routes>
    </div>
  )
}
