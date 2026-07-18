import { NavLink } from 'react-router-dom'
import { Moon, Sun, Menu, X } from 'lucide-react'
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'

function cn(...classes: (string | undefined | false)[]) {
  return classes.filter(Boolean).join(' ')
}

const navItems = [
  { to: '/keys', label: 'Keys' },
  { to: '/playground', label: 'Playground' },
  { to: '/models', label: 'Models' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/settings', label: 'Settings' },
]

function useDarkMode() {
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem('theme')
    return stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])

  function toggle() {
    setDark((prev) => {
      const next = !prev
      localStorage.setItem('theme', next ? 'dark' : 'light')
      return next
    })
  }

  return { dark, toggle }
}

function Navbar() {
  const { dark, toggle } = useDarkMode()
  const [mobileOpen, setMobileOpen] = useState(false)

  const { data: routingOverride } = useQuery<{ models: string[]; override_active: boolean }>({
    queryKey: ['routing-override'],
    queryFn: () => apiFetch('/api/settings/routing-override'),
    staleTime: 10_000,
  })

  return (
    <header className="sticky top-0 z-40 glass">
      <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6">
        {/* ── Logo ──────────────────────────────────────── */}
        <NavLink to="/" className="group flex items-center gap-2.5">
          <span className="relative flex size-7 items-center justify-center rounded-lg bg-gradient-accent shadow-glow transition-transform duration-200 group-hover:scale-110">
            <span className="size-3 rounded-sm bg-white/90" />
          </span>
          <span className="font-heading font-bold tracking-tight text-sm bg-gradient-accent bg-clip-text text-transparent">
            LLM Keypool
          </span>
        </NavLink>

        {/* ── Desktop nav ───────────────────────────────── */}
        <nav className="ml-10 hidden items-center gap-1 md:flex">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'relative px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200',
                  isActive
                    ? 'text-primary bg-primary/10'
                    : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                )
              }
            >
              {({ isActive }) => (
                <>
                  {item.label}
                  {isActive && (
                    <span className="absolute -bottom-[11px] left-1/2 -translate-x-1/2 size-1.5 rounded-full bg-primary animate-pulse-glow" />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* ── Right section ─────────────────────────────── */}
        <div className="ml-auto hidden items-center gap-2 md:flex">
          {routingOverride?.override_active && (
            <NavLink
              to="/settings"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-gradient-warm text-white shadow-sm hover:shadow-md transition-all"
            >
              <span className="inline-block size-1.5 rounded-full bg-white/80 animate-pulse" />
              Pinned: {routingOverride.models[0]}
            </NavLink>
          )}
          <button
            onClick={toggle}
            className="inline-flex items-center justify-center rounded-lg p-2 text-muted-foreground hover:text-accent hover:bg-accent/10 transition-all duration-200"
            aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
        </div>

        {/* ── Mobile hamburger ──────────────────────────── */}
        <div className="ml-auto md:hidden flex items-center gap-2">
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="inline-flex items-center justify-center rounded-lg p-2 text-muted-foreground hover:text-foreground hover:bg-secondary transition-all"
            aria-label="Toggle menu"
          >
            {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </div>

      {/* ── Mobile menu ─────────────────────────────────── */}
      {mobileOpen && (
        <div className="animate-slide-down border-t border-border/50 bg-background/95 backdrop-blur-lg md:hidden">
          <nav className="flex flex-col gap-0.5 p-3">
            {routingOverride?.override_active && (
              <NavLink
                to="/settings"
                onClick={() => setMobileOpen(false)}
                className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium bg-gradient-warm text-white"
              >
                <span className="inline-block size-1.5 rounded-full bg-white/80 animate-pulse" />
                Pinned: {routingOverride.models[0]}
              </NavLink>
            )}
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
            <button
              onClick={toggle}
              className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-secondary transition-all"
            >
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
              {dark ? 'Light mode' : 'Dark mode'}
            </button>
          </nav>
        </div>
      )}
    </header>
  )
}

export { Navbar }
