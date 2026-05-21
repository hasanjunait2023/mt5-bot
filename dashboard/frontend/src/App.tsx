import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { TradingProvider } from './contexts/TradingContext'
import { AuthGate } from './components/AuthGate'
import { Layout } from './components/layout/Layout'
import { Overview } from './pages/Overview'
import { Positions } from './pages/Positions'
import { History } from './pages/History'
import { BotsAgents } from './pages/BotsAgents'
import { SystemAgents } from './pages/SystemAgents'
import { Reports } from './pages/Reports'
import { Logs } from './pages/Logs'
import { Settings } from './pages/Settings'
import { EAs } from './pages/EAs'
import { CppPortfolio } from './pages/CppPortfolio'
import { TelegramHQ } from './pages/TelegramHQ'
import { Jtcc } from './pages/Jtcc'
import { Signals } from './pages/Signals'
import { Desk } from './pages/Desk'
import { Iconic } from './pages/Iconic'
import { Journal } from './pages/Journal'

export default function App() {
  return (
    <BrowserRouter>
      <AuthGate>
      <TradingProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="positions" element={<Positions />} />
            <Route path="history"   element={<History />} />
            <Route path="bots"      element={<BotsAgents />} />
            <Route path="system"    element={<SystemAgents />} />
            <Route path="reports"   element={<Reports />} />
            <Route path="logs"      element={<Logs />} />
            <Route path="settings"  element={<Settings />} />
            <Route path="eas"       element={<EAs />} />
            <Route path="cpp"       element={<CppPortfolio />} />
            <Route path="telegram"  element={<TelegramHQ />} />
            <Route path="jtcc"      element={<Jtcc />} />
            <Route path="signals"   element={<Signals />} />
            <Route path="desk"      element={<Desk />} />
            <Route path="iconic"    element={<Iconic />} />
            <Route path="journal"   element={<Journal />} />
          </Route>
        </Routes>
      </TradingProvider>
      </AuthGate>
    </BrowserRouter>
  )
}
