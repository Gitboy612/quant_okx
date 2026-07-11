import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { usePerformanceMode } from './hooks/usePerformanceMode'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import StrategiesPage from './pages/StrategiesPage'
import OrdersPage from './pages/OrdersPage'
import AccountsPage from './pages/AccountsPage'
import LogsPage from './pages/LogsPage'
import ApiLogsPage from './pages/ApiLogsPage'
import MonitoringPage from './pages/MonitoringPage'
import SettingsPage from './pages/SettingsPage'
import BacktestPage from './pages/BacktestPage'
import AnalyticsPage from './pages/AnalyticsPage'
import NotificationsPage from './pages/NotificationsPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#050711]">
        <div className="w-8 h-8 border-2 border-[rgba(0,212,170,0.15)] border-t-[#00D4AA] rounded-full animate-spin" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

/* Card stack transition */
const cardVariants = {
  initial: { opacity: 0, y: 20, scale: 0.96 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -15, scale: 0.97 },
}

const cardTransition = {
  type: 'spring' as const,
  stiffness: 300,
  damping: 30,
  mass: 0.8,
}

function PageCard({ children }: { children: React.ReactNode }) {
  const { performanceMode } = usePerformanceMode()

  if (performanceMode) {
    return <>{children}</>
  }

  return (
    <motion.div
      variants={cardVariants}
      transition={cardTransition}
      style={{ transformOrigin: 'center top', willChange: 'opacity, transform' }}
    >
      {children}
    </motion.div>
  )
}

function AnimatedRoutes() {
  const location = useLocation()

  return (
    <AnimatePresence mode="popLayout">
      <Routes location={location} key={location.pathname}>
        <Route path="/login" element={<PageCard><LoginPage /></PageCard>} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<PageCard><DashboardPage /></PageCard>} />
          <Route path="strategies" element={<PageCard><StrategiesPage /></PageCard>} />
          <Route path="orders" element={<PageCard><OrdersPage /></PageCard>} />
          <Route path="accounts" element={<PageCard><AccountsPage /></PageCard>} />
          <Route path="logs" element={<PageCard><LogsPage /></PageCard>} />
          <Route path="api-logs" element={<PageCard><ApiLogsPage /></PageCard>} />
          <Route path="monitoring" element={<PageCard><MonitoringPage /></PageCard>} />
          <Route path="backtest" element={<PageCard><BacktestPage /></PageCard>} />
          <Route path="analytics" element={<PageCard><AnalyticsPage /></PageCard>} />
          <Route path="notifications" element={<PageCard><NotificationsPage /></PageCard>} />
          <Route path="settings" element={<PageCard><SettingsPage /></PageCard>} />
        </Route>
      </Routes>
    </AnimatePresence>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AnimatedRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
