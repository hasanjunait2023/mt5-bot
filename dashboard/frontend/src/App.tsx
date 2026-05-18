import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { TradingProvider } from './contexts/TradingContext'
import { Layout } from './components/layout/Layout'
import { Overview } from './pages/Overview'
import { Positions } from './pages/Positions'
import { History } from './pages/History'
import { BotsAgents } from './pages/BotsAgents'
import { Reports } from './pages/Reports'
import { Logs } from './pages/Logs'
import { Settings } from './pages/Settings'
import { EAs } from './pages/EAs'

export default function App() {
  return (
    <BrowserRouter>
      <TradingProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="positions" element={<Positions />} />
            <Route path="history"   element={<History />} />
            <Route path="bots"      element={<BotsAgents />} />
            <Route path="reports"   element={<Reports />} />
            <Route path="logs"      element={<Logs />} />
            <Route path="settings"  element={<Settings />} />
            <Route path="eas"       element={<EAs />} />
          </Route>
        </Routes>
      </TradingProvider>
    </BrowserRouter>
  )
}
