import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Loader2 } from 'lucide-react'
import { HelpNode } from '@/components/ui/help-node'
import { HELP } from '@/lib/help-text'

interface AvailableModel {
  id: number
  platform: string
  model_id: string
  display_name: string
  tier: number
  intelligence_rank: number
  context_window: number | null
  supports_vision: boolean
  supports_tools: boolean
  is_free: boolean
  free_verified_by: 'freellmapi' | 'detection'
  key_id: number
  key_preview: string
  health: 'healthy' | 'cooldown' | 'error'
  cooldown_until: string | null
  size_label: string
}

const TIER_LABELS: Record<number, string> = {
  1: 'Frontier',
  2: 'High-Perf',
  3: 'Good OSS',
  4: 'Fallback',
}

const TIER_COLORS: Record<number, string> = {
  1: 'bg-emerald-500',
  2: 'bg-blue-500',
  3: 'bg-amber-500',
  4: 'bg-orange-500',
}

const HEALTH_DOT: Record<string, string> = {
  healthy: 'bg-emerald-500',
  cooldown: 'bg-yellow-500',
  error: 'bg-red-500',
}

export function AvailableModelsPanel() {
  const [showFreeOnly, setShowFreeOnly] = useState(true)
  const [providerFilter, setProviderFilter] = useState('')
  const [tierFilter, setTierFilter] = useState<number | null>(null)

  const { data: models, isLoading } = useQuery<AvailableModel[]>({
    queryKey: ['available-models', showFreeOnly, providerFilter, tierFilter],
    queryFn: () => {
      const params = new URLSearchParams()
      if (showFreeOnly) params.set('free_only', 'true')
      if (providerFilter) params.set('provider', providerFilter)
      if (tierFilter !== null) params.set('tier', String(tierFilter))
      return apiFetch(`/api/models/available?${params.toString()}`)
    },
    refetchInterval: 30_000,
  })

  const providers = useMemo(() => {
    if (!models) return []
    const seen = new Set<string>()
    return models.filter((m) => {
      if (seen.has(m.platform)) return false
      seen.add(m.platform)
      return true
    }).map((m) => m.platform).sort()
  }, [models])

  // Group by provider for the accordion-like display
  const grouped = useMemo(() => {
    if (!models) return new Map<string, AvailableModel[]>()
    const map = new Map<string, AvailableModel[]>()
    for (const m of models) {
      const list = map.get(m.platform) || []
      list.push(m)
      map.set(m.platform, list)
    }
    // Sort by average intelligence_rank within each group
    for (const [, list] of map) {
      list.sort((a, b) => a.intelligence_rank - b.intelligence_rank)
    }
    return map
  }, [models])

  const [expandedProvider, setExpandedProvider] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!models || models.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-muted/20 p-8 text-center">
        <p className="text-sm text-muted-foreground">
          No available models found.
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          Add an API key to unlock free models, or adjust your filters.
        </p>
      </div>
    )
  }

  const totalFree = models.filter((m) => m.free_verified_by === 'freellmapi').length
  const totalHealthy = models.filter((m) => m.health === 'healthy').length
  const totalCooldown = models.filter((m) => m.health === 'cooldown').length

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="grid grid-cols-4 gap-3">
        <div className="rounded-lg bg-accent/20 p-3">
          <div className="text-[10px] text-muted-foreground">Available</div>
          <div className="text-lg font-bold tabular-nums">{models.length}</div>
        </div>
        <div className="rounded-lg bg-emerald-500/10 p-3">
          <div className="text-[10px] text-emerald-600">Verified Free</div>
          <div className="text-lg font-bold tabular-nums text-emerald-600">{totalFree}</div>
        </div>
        <div className="rounded-lg bg-green-500/10 p-3">
          <div className="text-[10px] text-green-600">Healthy</div>
          <div className="text-lg font-bold tabular-nums text-green-600">{totalHealthy}</div>
        </div>
        <div className="rounded-lg bg-yellow-500/10 p-3">
          <div className="text-[10px] text-yellow-600">Cooldown</div>
          <div className="text-lg font-bold tabular-nums text-yellow-600">{totalCooldown}</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={showFreeOnly}
            onChange={(e) => setShowFreeOnly(e.target.checked)}
            className="rounded border-border"
          />
          <span className="text-xs font-medium text-muted-foreground select-none">Free only</span>
        </label>

        <select
          value={providerFilter}
          onChange={(e) => setProviderFilter(e.target.value)}
          className="h-7 rounded border border-input bg-background px-2 text-[11px] focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value="">All providers</option>
          {providers.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>

        <select
          value={tierFilter ?? ''}
          onChange={(e) => setTierFilter(e.target.value ? parseInt(e.target.value) : null)}
          className="h-7 rounded border border-input bg-background px-2 text-[11px] focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value="">All tiers</option>
          {[1, 2, 3, 4].map((t) => (
            <option key={t} value={t}>Tier {t} — {TIER_LABELS[t]}</option>
          ))}
        </select>

        <span className="text-[10px] text-muted-foreground ml-auto">
          Updated every 30s
        </span>
      </div>

      {/* Provider-grouped model list */}
      <div className="space-y-2">
        {Array.from(grouped.entries()).sort().map(([platform, platformModels]) => {
          const isExpanded = expandedProvider === platform
          const healthy = platformModels.filter((m) => m.health === 'healthy').length
          const cooldown = platformModels.filter((m) => m.health === 'cooldown').length
          const verified = platformModels.filter((m) => m.free_verified_by === 'freellmapi').length

          return (
            <div key={platform} className="rounded-lg border border-border overflow-hidden">
              {/* Provider header — clickable accordion */}
              <button
                onClick={() => setExpandedProvider(isExpanded ? null : platform)}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-accent/20 transition-colors text-left"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-sm font-semibold">{platform}</span>
                  <span className="text-[10px] text-muted-foreground tabular-nums">
                    {platformModels.length} models
                  </span>
                </div>
                <div className="flex items-center gap-2 ml-auto">
                  {verified > 0 && (
                    <Badge className="bg-emerald-500/10 text-emerald-600 border-emerald-200 text-[10px]">
                      {verified} verified free
                    </Badge>
                  )}
                  {cooldown > 0 && (
                    <Badge className="bg-yellow-500/10 text-yellow-600 border-yellow-200 text-[10px]">
                      {cooldown} cooling
                    </Badge>
                  )}
                  {healthy > 0 && (
                    <Badge className="bg-green-500/10 text-green-600 border-green-200 text-[10px]">
                      {healthy} ready
                    </Badge>
                  )}
                  <span className="text-xs text-muted-foreground">{isExpanded ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* Model rows */}
              {isExpanded && (
                <div className="border-t border-border">
                  {platformModels.map((m) => (
                    <div
                      key={`${m.platform}:${m.model_id}`}
                      className="flex items-center gap-3 px-4 py-2 border-b border-border/50 last:border-0 hover:bg-muted/20 transition-colors"
                    >
                      {/* Health dot */}
                      <span
                        className={`size-2 rounded-full shrink-0 ${HEALTH_DOT[m.health] || HEALTH_DOT.healthy}`}
                        title={m.health}
                      />

                      {/* Model info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-xs font-medium truncate">{m.model_id}</span>
                          {m.free_verified_by === 'freellmapi' && (
                            <Badge className="bg-emerald-500/10 text-emerald-600 border-emerald-200 text-[9px] px-1 py-0">
                              FREE
                            </Badge>
                          )}
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          {m.display_name !== m.model_id ? m.display_name : m.size_label}
                          {m.context_window && <> · {(m.context_window / 1000).toFixed(0)}K ctx</>}
                        </div>
                      </div>

                      {/* Tier badge */}
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium text-white ${TIER_COLORS[m.tier]}`}>
                        T{m.tier}<HelpNode content={HELP.modelTier} side="top" />
                      </span>

                      {/* Capabilities */}
                      <div className="flex gap-1">
                        {m.supports_tools && <span className="text-[10px] text-muted-foreground border border-border rounded px-1">tools</span>}
                        {m.supports_vision && <span className="text-[10px] text-muted-foreground border border-border rounded px-1">vision</span>}
                      </div>

                      {/* Key */}
                      <span className="text-[10px] font-mono text-muted-foreground tabular-nums" title={`key_id: ${m.key_id}`}>
                        {m.key_preview}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
