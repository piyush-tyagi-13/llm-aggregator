import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Navbar } from '@/components/navbar'
import { KeysPage } from '@/pages/KeysPage'
import { LogsPage } from '@/pages/LogsPage'
import { ModelsPage } from '@/pages/ModelsPage'
import { AnalyticsPage } from '@/pages/AnalyticsPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { ErrorBoundary } from '@/components/ui/error-boundary'
import { useEffect } from 'react'

/** Scrolls to top on route change and triggers stagger re-animation. */
function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

/** Wraps the page content area with a stagger container keyed on route. */
function PageShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()
  return (
    <div key={pathname} data-stagger className="animate-fade-in-up">
      {children}
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ScrollToTop />
      <div className="min-h-screen bg-background">
        <Navbar />
        <main className="mx-auto max-w-6xl px-4 sm:px-6 py-8">
          <Routes>
            <Route
              path="/"
              element={
                <PageShell>
                  <Navigate to="/keys" replace />
                </PageShell>
              }
            />
            <Route
              path="/keys"
              element={
                <PageShell>
                  <ErrorBoundary>
                    <KeysPage />
                  </ErrorBoundary>
                </PageShell>
              }
            />
            <Route
              path="/logs"
              element={
                <PageShell>
                  <ErrorBoundary>
                    <LogsPage />
                  </ErrorBoundary>
                </PageShell>
              }
            />
            <Route
              path="/models"
              element={
                <PageShell>
                  <ErrorBoundary>
                    <ModelsPage />
                  </ErrorBoundary>
                </PageShell>
              }
            />
            <Route
              path="/analytics"
              element={
                <PageShell>
                  <ErrorBoundary>
                    <AnalyticsPage />
                  </ErrorBoundary>
                </PageShell>
              }
            />
            <Route
              path="/settings"
              element={
                <PageShell>
                  <ErrorBoundary>
                    <SettingsPage />
                  </ErrorBoundary>
                </PageShell>
              }
            />
            <Route
              path="*"
              element={
                <PageShell>
                  <Navigate to="/keys" replace />
                </PageShell>
              }
            />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
