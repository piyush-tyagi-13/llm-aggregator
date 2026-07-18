import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Loader2, Key } from 'lucide-react'
import { HelpNode } from '@/components/ui/help-node'
import { HELP } from '@/lib/help-text'

interface SampleModel {
  model_id: string
  display_name: string
  tier: number
  intelligence_rank: number
  context_window: number | null
}

interface UnlockableGroup {
  provider: string
  model_count: number
  samples: SampleModel[]
}

const TIER_COLORS: Record<number, string> = {
  1: 'bg-emerald-500',
  2: 'bg-blue-500',
  3: 'bg-amber-500',
  4: 'bg-orange-500',
}

export function UnlockableModelsPanel() {
  const { data: groups, isLoading } = useQuery<UnlockableGroup[]>({
    queryKey: ['unlockable-models'],
    queryFn: () => apiFetch('/api/models/unlockable'),
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!groups || groups.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-muted/20 p-8 text-center">
        <Key className="size-8 mx-auto mb-3 text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">
          All available free models are unlocked.
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          Every provider in the FreeLLMAPI catalog has at least one key.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <Key className="size-4 text-muted-foreground" />
        <p className="text-xs text-muted-foreground">
          Add a key to unlock these providers and their free models.
        </p>
      </div>

      {groups.map((g) => (
        <div key={g.provider} className="rounded-lg border border-border overflow-hidden">
          {/* Provider header */}
          <div className="flex items-center justify-between px-4 py-2.5 bg-accent/10">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">{g.provider}</span>
              <Badge variant="outline" className="text-[10px] font-mono">
                {g.model_count} free models
              </Badge>
            </div>
            <div className="flex items-center gap-1">
              <HelpNode content={HELP.unlockableModels} side="left" />
              <button
                onClick={() => window.location.href = `/keys?provider=${g.provider}`}
                className="text-[11px] text-primary hover:text-primary/80 transition-colors font-medium"
              >
                Add key →
              </button>
            </div>
          </div>

          {/* Sample models */}
          <div className="divide-y divide-border/50">
            {g.samples.map((s) => (
              <div key={s.model_id} className="flex items-center gap-3 px-4 py-2">
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs font-medium truncate">{s.model_id}</div>
                  {s.display_name !== s.model_id && (
                    <div className="text-[10px] text-muted-foreground truncate">{s.display_name}</div>
                  )}
                </div>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium text-white ${TIER_COLORS[s.tier]}`}>
                  T{s.tier}
                </span>
                {s.context_window && (
                  <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
                    {(s.context_window / 1000).toFixed(0)}K
                  </span>
                )}
              </div>
            ))}
          </div>

          {g.model_count > g.samples.length && (
            <div className="px-4 py-1.5 text-[10px] text-muted-foreground text-center border-t border-border/50">
              +{g.model_count - g.samples.length} more models
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
