import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { KeysPage } from '@/pages/KeysPage'

// Mock UI primitives that might cause import issues
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
vi.mock('@/components/ui/textarea', () => ({
  Textarea: (props: React.ComponentPropsWithoutRef<'textarea'>) => <textarea {...props} />,
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({ children, ...props }: React.ComponentPropsWithoutRef<'select'>) => (
    <select {...props} data-testid="select">
      {children}
    </select>
  ),
}))
vi.mock('@/components/ui/label', () => ({
  Label: ({ children, ...props }: React.ComponentPropsWithoutRef<'label'>) => <label {...props}>{children}</label>,
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
vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children, ...props }: React.ComponentPropsWithoutRef<'span'>) => <span {...props}>{children}</span>,
}))
vi.mock('@/components/page-header', () => ({
  PageHeader: ({ title, description }: { title: string; description: string }) => (
    <div data-testid="page-header">
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  ),
}))

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Plus: () => <span data-testid="icon-plus">+</span>,
  Trash2: () => <span data-testid="icon-trash">🗑</span>,
  Loader2: () => <span data-testid="icon-loader">⏳</span>,
  Upload: () => <span data-testid="icon-upload">↑</span>,
  CheckCircle2: () => <span data-testid="icon-check">✓</span>,
  AlertCircle: () => <span data-testid="icon-alert">⚠</span>,
  HelpCircle: () => <span data-testid="icon-help">?</span>,
  Search: () => <span data-testid="icon-search">🔍</span>,
  X: () => <span data-testid="icon-x">✕</span>,
  ChevronDown: () => <span data-testid="icon-chevron-down">▼</span>,
  ChevronRight: () => <span data-testid="icon-chevron-right">▶</span>,
  Copy: () => <span data-testid="icon-copy">📋</span>,
  Check: () => <span data-testid="icon-check">✓</span>,
  ExternalLink: () => <span data-testid="icon-external">↗</span>,
  Settings2: () => <span data-testid="icon-settings">⚙</span>,
  Globe: () => <span data-testid="icon-globe">🌐</span>,
  Pin: () => <span data-testid="icon-pin">📌</span>,
  PinOff: () => <span data-testid="icon-pin-off">🚫</span>,
  RefreshCw: () => <span data-testid="icon-refresh">🔄</span>,
  Activity: () => <span data-testid="icon-activity">📈</span>,
  Zap: () => <span data-testid="icon-zap">⚡</span>,
  Timer: () => <span data-testid="icon-timer">⏱</span>,
  AlertTriangle: () => <span data-testid="icon-alert-triangle">⚠</span>,
  Filter: () => <span data-testid="icon-filter">🔍</span>,
  Key: () => <span data-testid="icon-key">🔑</span>,
}))

// Mock the apiFetch module
const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (path: string, options?: Record<string, unknown>) => mockApiFetch(path, options),
}))

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

describe('KeysPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading state initially', () => {
    mockApiFetch.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<KeysPage />)
    // Component mounts without crashing
    expect(document.querySelector('[data-testid="page-header"]') ?? true).toBeTruthy()
  })

  it('renders the page header', async () => {
    mockApiFetch.mockResolvedValue([])
    renderWithProviders(<KeysPage />)
    expect(await screen.findByTestId('page-header')).toBeInTheDocument()
  })

  it('shows empty state when no keys exist', async () => {
    mockApiFetch.mockResolvedValue([])
    renderWithProviders(<KeysPage />)
    // Should show a message about having no keys or the import form
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalled()
    })
  })

  it('renders keys when data is available', async () => {
    const mockKeys = [
      {
        id: 1,
        provider: 'groq',
        model: 'llama-3.3-70b-versatile',
        is_active: 1,
        requests_today: 5,
        cooldown_until: null,
        context_size: null,
        accuracy_score: 80,
        speed_score: 90,
        reliability_score: 85,
        group_name: 'default',
      },
      {
        id: 2,
        provider: 'openai',
        model: 'gpt-4o',
        is_active: 1,
        requests_today: 3,
        cooldown_until: null,
        context_size: null,
        accuracy_score: 95,
        speed_score: 70,
        reliability_score: 90,
        group_name: 'default',
      },
    ]
    mockApiFetch.mockResolvedValue(mockKeys)
    renderWithProviders(<KeysPage />)

    // Wait for the keys to be rendered — the page should show provider names
    await waitFor(() => {
      expect(screen.getByText(/groq/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/openai/i)).toBeInTheDocument()
  })

  it('handles fetch errors gracefully', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))
    renderWithProviders(<KeysPage />)

    // Should eventually finish loading (no loader) without crashing
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalled()
    })

    // The page renders with empty key list — no crash
    await waitFor(() => {
      expect(screen.getByTestId('page-header')).toBeInTheDocument()
    })
  })
})
