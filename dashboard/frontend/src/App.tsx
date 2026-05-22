import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { TradingProvider } from './contexts/TradingContext'
import { AuthGate } from './components/AuthGate'
import { Layout } from './components/layout/Layout'

const Overview     = lazy(() => import('./pages/Overview').then(m => ({ default: m.Overview })))
const Positions    = lazy(() => import('./pages/Positions').then(m => ({ default: m.Positions })))
const History      = lazy(() => import('./pages/History').then(m => ({ default: m.History })))
const BotsAgents   = lazy(() => import('./pages/BotsAgents').then(m => ({ default: m.BotsAgents })))
const SystemAgents = lazy(() => import('./pages/SystemAgents').then(m => ({ default: m.SystemAgents })))
const Reports      = lazy(() => import('./pages/Reports').then(m => ({ default: m.Reports })))
const Logs         = lazy(() => import('./pages/Logs').then(m => ({ default: m.Logs })))
const Settings     = lazy(() => import('./pages/Settings').then(m => ({ default: m.Settings })))
const EAs          = lazy(() => import('./pages/EAs').then(m => ({ default: m.EAs })))
const CppPortfolio = lazy(() => import('./pages/CppPortfolio').then(m => ({ default: m.CppPortfolio })))
const TelegramHQ   = lazy(() => import('./pages/TelegramHQ').then(m => ({ default: m.TelegramHQ })))
const Jtcc         = lazy(() => import('./pages/Jtcc').then(m => ({ default: m.Jtcc })))
const Signals      = lazy(() => import('./pages/Signals').then(m => ({ default: m.Signals })))
const Desk         = lazy(() => import('./pages/Desk').then(m => ({ default: m.Desk })))
const Iconic       = lazy(() => import('./pages/Iconic').then(m => ({ default: m.Iconic })))
const Journal      = lazy(() => import('./pages/Journal').then(m => ({ default: m.Journal })))
const Scalp        = lazy(() => import('./pages/Scalp').then(m => ({ default: m.Scalp })))

function PageLoader() {
  return <div className="min-h-[60vh] grid place-items-center text-text-muted text-sm animate-pulse">Loading…</div>
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthGate>
      <TradingProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Suspense fallback={<PageLoader />}><Overview /></Suspense>} />
            <Route path="positions" element={<Suspense fallback={<PageLoader />}><Positions /></Suspense>} />
            <Route path="history"   element={<Suspense fallback={<PageLoader />}><History /></Suspense>} />
            <Route path="bots"      element={<Suspense fallback={<PageLoader />}><BotsAgents /></Suspense>} />
            <Route path="system"    element={<Suspense fallback={<PageLoader />}><SystemAgents /></Suspense>} />
            <Route path="reports"   element={<Suspense fallback={<PageLoader />}><Reports /></Suspense>} />
            <Route path="logs"      element={<Suspense fallback={<PageLoader />}><Logs /></Suspense>} />
            <Route path="settings"  element={<Suspense fallback={<PageLoader />}><Settings /></Suspense>} />
            <Route path="eas"       element={<Suspense fallback={<PageLoader />}><EAs /></Suspense>} />
            <Route path="cpp"       element={<Suspense fallback={<PageLoader />}><CppPortfolio /></Suspense>} />
            <Route path="telegram"  element={<Suspense fallback={<PageLoader />}><TelegramHQ /></Suspense>} />
            <Route path="jtcc"      element={<Suspense fallback={<PageLoader />}><Jtcc /></Suspense>} />
            <Route path="signals"   element={<Suspense fallback={<PageLoader />}><Signals /></Suspense>} />
            <Route path="desk"      element={<Suspense fallback={<PageLoader />}><Desk /></Suspense>} />
            <Route path="iconic"    element={<Suspense fallback={<PageLoader />}><Iconic /></Suspense>} />
            <Route path="journal"   element={<Suspense fallback={<PageLoader />}><Journal /></Suspense>} />
            <Route path="scalp"    element={<Suspense fallback={<PageLoader />}><Scalp /></Suspense>} />
          </Route>
        </Routes>
      </TradingProvider>
      </AuthGate>
    </BrowserRouter>
  )
}
