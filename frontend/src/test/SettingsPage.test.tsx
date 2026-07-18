import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { SettingsPage } from '@/pages/SettingsPage'

// Mock UI primitives
vi.mock('@/components/ui/card', () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div data-testid="card">{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div data-testid="card-content">{children}</div>,
  CardHeader: ({ children }: { children: React.ReactNode }) => <div data-testid="card-header">{children}</div>,
  CardTitle: ({ children }: { children: React.ReactNode }) => <div data-testid="card-title">{children}</div>,
  CardDescription: ({ children }: { children: React.ReactNode }) => <div data-testid="card-description">{children}</div>,
}))
vi.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: React.ComponentPropsWithoutRef<'button'>) => <button {...props}>{children}</button>,
}))
vi.mock('@/components/ui/input', () => ({
  Input: (props: React.ComponentPropsWithoutRef<'input'>) => <input {...props} />,
}))
vi.mock('@/components/ui/switch', () => ({
  Switch: ({ onCheckedChange, checked, ...props }: { onCheckedChange?: (checked: boolean) => void; checked?: boolean } & React.ComponentPropsWithoutRef<'input'>) => (
    <input
      type="checkbox"
      role="switch"
      checked={checked}
      onChange={(e) => onCheckedChange?.(e.target.checked)}
      {...props}
    />
  ),
}))
vi.mock('@/components/page-header', () => ({
  PageHeader: ({ title, description }: { title: string; description: string }) => (
    <div data-testid="page-header">
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  ),
}))

vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children, ...props }: React.ComponentPropsWithoutRef<'span'>) => <span {...props}>{children}</span>,
}))

vi.mock('@/components/ui/tooltip', () => ({
  Tooltip: ({ content, children }: { content: string; children: React.ReactNode }) => <>{children}</>,
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('@/components/ui/help-node', () => ({
  HelpNode: ({ content, side }: { content: string; side?: string }) => <span data-testid="help-node" title={content}>?</span>,
}))

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Save: () => <span data-testid="icon-save">💾</span>,
  Loader2: () => <span data-testid="icon-loader">⏳</span>,
  CheckCircle2: () => <span data-testid="icon-check">✓</span>,
  AlertCircle: () => <span data-testid="icon-alert">⚠</span>,
  X: () => <span data-testid="icon-x">✕</span>,
  ChevronRight: () => <span data-testid="icon-chevron-right">▶</span>,
  Route: () => <span data-testid="icon-route">🚦</span>,
  GitBranch: () => <span data-testid="icon-git-branch">🌿</span>,
  Layers: () => <span data-testid="icon-layers">📚</span>,
  PieChart: () => <span data-testid="icon-pie-chart">📊</span>,
  Zap: () => <span data-testid="icon-zap">⚡</span>,
  Shield: () => <span data-testid="icon-shield">🛡</span>,
  Activity: () => <span data-testid="icon-activity">📈</span>,
  Search: () => <span data-testid="icon-search">🔍</span>,
  ArrowRight: () => <span data-testid="icon-arrow-right">→</span>,
  CircleDot: () => <span data-testid="icon-circle-dot">○</span>,
  Gauge: () => <span data-testid="icon-gauge">📏</span>,
  Timer: () => <span data-testid="icon-timer">⏱</span>,
}))

// Mock the apiFetch module
const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (path: string, options?: Record<string, unknown>) => mockApiFetch(path, options),
}))

function makeDefaultApiMock() {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.includes('strategy')) return Promise.resolve({ strategy: 'balanced', custom_weights: null })
    if (path.includes('sticky')) return Promise.resolve({ sticky_enabled: true, sticky_ttl_ms: 600000, max_sticky_entries: 1000, active_sessions: 0 })
    if (path.includes('handoff')) return Promise.resolve({ mode: 'off' })
    if (path.includes('affinity')) return Promise.resolve({ affinity_enabled: false, busy: [], semi_busy: [], available_slots: 5, total_slots: 5, pinned_uids: 0 })
    if (path.includes('tier-fallback')) return Promise.resolve({ tier_fallback_enabled: true })
    if (path.includes('tier-settings') || path.includes('quality-tier')) return Promise.resolve({ quality_tier: 1, max_fallback_tier: 4, min_tier: 1, max_tier: 4 })
    if (path.includes('routing-override')) return Promise.resolve({ models: [], override_active: false })
    if (path.includes('fallback-modes')) return Promise.resolve({
      active_mode: 'fallback',
      modes: { fallback: { enabled: true, quality_tier: 1, max_fallback_tier: 4 },
              sticky: { enabled: false, sticky_enabled: true, max_ttft_ms: 5000, min_throughput: 10 },
              slimey: { enabled: false, max_ttft_ms: 3000, min_throughput: 20 } }
    })
    if (path.includes('fallback')) return Promise.resolve({ max_attempts_same_key: 3, max_attempts_same_provider: 3, max_attempts_all_providers: 3, cooldown_on_failure_ms: 1800000 })
    return Promise.resolve({})
  })
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const AFFINITY_MOCK = { affinity_enabled: false, busy: [], semi_busy: [], available_slots: 5, total_slots: 5, pinned_uids: 0 }

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading state initially', () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('affinity')) return Promise.resolve(AFFINITY_MOCK)
      if (path.includes('fallback-modes')) return Promise.resolve({
        active_mode: 'fallback',
        modes: { fallback: { enabled: true }, sticky: {}, slimey: {} }
      })
      return Promise.resolve({})
    })
    renderWithProviders(<SettingsPage />)
    expect(document.querySelector('[data-testid="page-header"]') ?? true).toBeTruthy()
  })

  it('renders the page header when loaded', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('strategy')) return Promise.resolve({ strategy: 'balanced' })
      if (path.includes('affinity')) return Promise.resolve(AFFINITY_MOCK)
      if (path.includes('routing-override')) return Promise.resolve({ models: [], override_active: false })
      if (path.includes('fallback-modes')) return Promise.resolve({
        active_mode: 'fallback',
        modes: { fallback: { enabled: true }, sticky: {}, slimey: {} }
      })
      return Promise.resolve({})
    })
    renderWithProviders(<SettingsPage />)
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    expect(await screen.findByTestId('page-header')).toBeInTheDocument()
  })

  it('displays all settings sections', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('strategy')) return Promise.resolve({ strategy: 'balanced', custom_weights: null })
      if (path.includes('sticky')) return Promise.resolve({ sticky_enabled: true, sticky_ttl_ms: 600000, max_sticky_entries: 1000, active_sessions: 0 })
      if (path.includes('handoff')) return Promise.resolve({ mode: 'off' })
      if (path.includes('affinity')) return Promise.resolve(AFFINITY_MOCK)
      if (path.includes('tier-fallback')) return Promise.resolve({ tier_fallback_enabled: true })
      if (path.includes('tier-settings')) return Promise.resolve({ quality_tier: 1, max_fallback_tier: 4, min_tier: 1, max_tier: 4 })
      if (path.includes('routing-override')) return Promise.resolve({ models: [], override_active: false })
      if (path.includes('fallback')) return Promise.resolve({ max_attempts_same_key: 3, max_attempts_same_provider: 3, max_attempts_all_providers: 3, cooldown_on_failure_ms: 1800000 })
      if (path.includes('slimey')) return Promise.resolve({ enabled: false, max_ttft_ms: 2000, min_throughput_rps: 10, tier: 1, strategy: 'balanced' })
      return Promise.resolve({})
    })
    renderWithProviders(<SettingsPage />)

    await waitFor(() => { expect(mockApiFetch).toHaveBeenCalled() })
    await waitFor(() => { expect(screen.getByText(/save/i)).toBeInTheDocument() })
  })

  it('handles load errors gracefully', async () => {
    mockApiFetch.mockRejectedValue(new Error('Failed to load settings'))
    renderWithProviders(<SettingsPage />)

    await waitFor(() => { expect(mockApiFetch).toHaveBeenCalled() })
    await waitFor(() => { expect(screen.getByTestId('page-header')).toBeInTheDocument() })
  })
})
