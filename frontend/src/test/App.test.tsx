import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from '@/App'

// Mock all page components to avoid API calls
vi.mock('@/pages/KeysPage', () => ({
  KeysPage: () => <div data-testid="keys-page">Keys Page</div>,
}))
vi.mock('@/pages/LogsPage', () => ({
  LogsPage: () => <div data-testid="logs-page">Logs Page</div>,
}))
vi.mock('@/pages/ModelsPage', () => ({
  ModelsPage: () => <div data-testid="models-page">Models Page</div>,
}))
vi.mock('@/pages/AnalyticsPage', () => ({
  AnalyticsPage: () => <div data-testid="analytics-page">Analytics Page</div>,
}))
vi.mock('@/pages/SettingsPage', () => ({
  SettingsPage: () => <div data-testid="settings-page">Settings Page</div>,
}))
vi.mock('@/components/navbar', () => ({
  Navbar: () => <nav data-testid="navbar">Navbar</nav>,
}))

describe('App', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/keys')
  })

  it('renders the navbar', () => {
    render(<App />)
    expect(screen.getByTestId('navbar')).toBeInTheDocument()
  })

  it('renders KeysPage at /keys route', () => {
    render(<App />)
    expect(screen.getByTestId('keys-page')).toBeInTheDocument()
  })

  it('redirects / to /keys', () => {
    window.history.pushState({}, '', '/')
    render(<App />)
    expect(screen.getByTestId('keys-page')).toBeInTheDocument()
  })

  it('renders ModelsPage at /models route', () => {
    window.history.pushState({}, '', '/models')
    render(<App />)
    expect(screen.getByTestId('models-page')).toBeInTheDocument()
  })

  it('renders SettingsPage at /settings route', () => {
    window.history.pushState({}, '', '/settings')
    render(<App />)
    expect(screen.getByTestId('settings-page')).toBeInTheDocument()
  })

  it('renders AnalyticsPage at /analytics route', () => {
    window.history.pushState({}, '', '/analytics')
    render(<App />)
    expect(screen.getByTestId('analytics-page')).toBeInTheDocument()
  })
})
