import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Loader2, Activity, RefreshCw } from 'lucide-react'
import { HelpNode } from '@/components/ui/help-node'
import { HELP } from '@/lib/help-text'

interface CooldownRow {
  key_id: number
  model_db_id: number
  cooldown_until: string | null
  cooldown_count: number
  updated_at: string
  provider: string
  model_id: string
  model_platform: string
}

interface AvailableModel {
  id: number
  platform: string
  model_id: string
  health: 'healthy' | 'cooldown' | 'error'
  cooldown_until: string | null
  tier: number
}

function formatCountdown(iso: string | null): string {
  if (!iso) return '—'
  const remaining = new Date(iso).getTime() - Date.now()
  if (remaining <= 0) return 'Expired'
  const secs = Math.ceil(remaining / 1000)
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.ceil(secs / 60)}m ${secs % 60}s`
  return `${Math.ceil(secs / 3600)}h ${Math.ceil((secs % 3600) / 60)}m`
}

export function ModelHealthPanel() {
  const queryClient = useQueryClient()

  const { data: available } = useQuery<AvailableModel[]>({
    queryKey: ['available-models-health'],
    queryFn: () => apiFetch('/api/models/available?free_only=true'),
    refetchInterval: 15_000,
  })

  const { data: cooldowns } = useQuery<CooldownRow[]>({
    queryKey: ['model-cooldowns'],
    queryFn: () => apiFetch('/api/models/cooldowns'),
    refetchInterval: 15_000,
  })

  const healthCheckMutation = useMutation({
    mutationFn: () => apiFetch('/api/health-check', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['available-models-health'] })
      queryClient.invalidateQueries({ queryKey: ['model-cooldowns'] })
    },
  })

  if (!available && !cooldowns) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const healthyCount = available?.filter((m) => m.health === 'healthy').length ?? 0
  const cooldownCount = available?.filter((m) => m.health === 'cooldown').length ?? 0
  const activeCooldowns = cooldowns?.filter((c) => c.cooldown_until && new Date(c.cooldown_until) > new Date()) ?? []

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-green-500/10 p-3">
          <div className="text-[10px] text-green-600">Healthy Models</div>
          <div className="text-lg font-bold tabular-nums text-green-600">{healthyCount}</div>
        </div>
        <div className="rounded-lg bg-yellow-500/10 p-3">
          <div className="text-[10px] text-yellow-600">On Cooldown</div>
          <div className="text-lg font-bold tabular-nums text-yellow-600">{cooldownCount}</div>
        </div>
        <div className="rounded-lg bg-red-500/10 p-3">
          <div className="text-[10px] text-red-600">Active Cooldowns</div>
          <div className="text-lg font-bold tabular-nums text-red-600">{activeCooldowns.length}</div>
        </div>
      </div>

      {/* Currently cooling models from available list */}
      {available && available.filter((m) => m.health === 'cooldown').length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <Activity className="size-3" />
            Models on cooldown
          </h3>
          <div className="space-y-1">
            {available
              .filter((m) => m.health === 'cooldown')
              .sort((a, b) => (a.cooldown_until ?? '').localeCompare(b.cooldown_until ?? ''))
              .map((m) => (
                <div key={`${m.platform}:${m.model_id}`} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border bg-yellow-500/5">
                  <span className="size-2 rounded-full bg-yellow-500 shrink-0" />
                  <span className="font-mono text-xs flex-1 truncate">{m.model_id}</span>
                  <Badge variant="outline" className="text-[10px]">{m.platform}</Badge>
                  <span className="text-[10px] font-mono text-yellow-600 tabular-nums">
                    {formatCountdown(m.cooldown_until)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {activeCooldowns.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
              Rate-limit history <HelpNode content={HELP.circuitBreaker} side="top" />
            </h3>
            <Button
              variant="outline"
              size="xs"
              onClick={() => healthCheckMutation.mutate()}
              disabled={healthCheckMutation.isPending}
              className="h-7 px-2 text-xs"
            >
              {healthCheckMutation.isPending ? (
                <Loader2 className="size-3 animate-spin mr-1" />
              ) : (
                <RefreshCw className="size-3 mr-1" />
              )}
              Health Check
            </Button>
          </div>
          <div className="rounded-lg border border-border overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="text-left font-medium text-muted-foreground px-3 py-2">Model</th>
                  <th className="text-left font-medium text-muted-foreground px-3 py-2">Provider</th>
                  <th className="text-right font-medium text-muted-foreground px-3 py-2">Count</th>
                  <th className="text-right font-medium text-muted-foreground px-3 py-2">Cooldown</th>
                  <th className="text-right font-medium text-muted-foreground px-3 py-2">Expires</th>
                </tr>
              </thead>
              <tbody>
                {activeCooldowns.slice(0, 50).map((c) => (
                  <tr key={`${c.key_id}:${c.model_db_id}`} className="border-b border-border/50 last:border-0 hover:bg-muted/20">
                    <td className="px-3 py-1.5 font-mono">{c.model_id}</td>
                    <td className="px-3 py-1.5">{c.provider}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{c.cooldown_count}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-yellow-600">
                      {formatCountdown(c.cooldown_until)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                      {c.cooldown_until ? new Date(c.cooldown_until).toLocaleTimeString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {healthyCount > 0 && cooldownCount === 0 && activeCooldowns.length === 0 && (
        <div className="rounded-lg border border-border bg-emerald-500/5 p-6 text-center">
          <Activity className="size-8 mx-auto mb-2 text-emerald-500/40" />
          <p className="text-sm text-emerald-600 font-medium">All models healthy</p>
          <p className="text-xs text-muted-foreground mt-1">No rate limits or cooldowns detected.</p>
        </div>
      )}
    </div>
  )
}
