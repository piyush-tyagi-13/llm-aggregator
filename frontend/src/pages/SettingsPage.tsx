import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { HelpNode } from '@/components/ui/help-node'
import { HELP } from '@/lib/help-text'
import {
  Save, Loader2, CheckCircle2, AlertCircle, X, ChevronRight,
  Route, GitBranch, Layers, PieChart, Zap, Shield, Activity, Search,
  ArrowRight, CircleDot, Gauge, Timer,
} from 'lucide-react'

const STRATEGIES = ['auto', 'priority', 'balanced', 'smartest', 'fastest', 'reliable', 'custom'] as const

interface FallbackConfig {
  max_attempts_same_key: number
  max_attempts_same_provider: number
  max_attempts_all_providers: number
  cooldown_on_failure_ms: number
}

interface StickyConfig {
  sticky_enabled: boolean
  sticky_ttl_ms: number
  max_sticky_entries: number
  active_sessions: number
}

interface TierSettings {
  quality_tier: number
  max_fallback_tier: number
  min_tier: number
  max_tier: number
}

interface AffinityConfig {
  affinity_enabled: boolean
  available_slots: number
  total_slots: number
  busy: { key_id: number; model_name: string }[]
  semi_busy: { key_id: number; model_name: string; remaining_secs: number }[]
  pinned_uids: number
}

interface RoutingOverride {
  models: string[]
  override_active: boolean
}

function CollapsibleSection({
  title, description, icon, defaultOpen, children,
}: {
  title: string
  description?: string
  icon?: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen ?? false)
  return (
    <Card>
      <button onClick={() => setOpen(!open)} className="w-full text-left">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {icon}
              <div>
                <CardTitle>{title}</CardTitle>
                {description && <CardDescription>{description}</CardDescription>}
              </div>
            </div>
            <div className="text-muted-foreground transition-transform duration-200" style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}>
              <ChevronRight className="size-4" />
            </div>
          </div>
        </CardHeader>
      </button>
      {open && <CardContent>{children}</CardContent>}
    </Card>
  )
}

function RoutingPipelineCard() {
  const { data: strData } = useQuery<{ strategy: string }>({
    queryKey: ['routing-strategy'],
    queryFn: () => apiFetch('/api/settings/routing-strategy'),
  })
  const { data: stkData } = useQuery<StickyConfig>({
    queryKey: ['sticky'],
    queryFn: () => apiFetch('/api/settings/sticky'),
  })
  const { data: affData } = useQuery<AffinityConfig>({
    queryKey: ['affinity'],
    queryFn: () => apiFetch('/api/settings/affinity'),
  })
  const { data: tfData } = useQuery<{ tier_fallback_enabled: boolean }>({
    queryKey: ['tier-fallback'],
    queryFn: () => apiFetch('/api/settings/tier-fallback'),
  })

  const strategy = strData?.strategy ?? 'balanced'
  const stickyEnabled = stkData?.sticky_enabled ?? false
  const affinityEnabled = affData?.affinity_enabled ?? false
  const tierFallback = tfData?.tier_fallback_enabled ?? true

  const pipelineSteps = [
    { label: 'Capability Filter', active: true, desc: 'Match request capabilities to model features' },
    { label: 'Tier Filter', active: tierFallback, desc: 'Filter by quality tier range' },
    { label: 'Affinity', active: affinityEnabled, desc: 'Pin UIDs to key+model pairs' },
    { label: 'Sticky Sessions', active: stickyEnabled, desc: 'Persist routing for session duration' },
    { label: 'Rotation', active: true, desc: `Strategy: ${strategy}` },
    { label: 'Circuit Breaker', active: true, desc: 'Skip failing keys automatically' },
    { label: 'Provider Dispatch', active: true, desc: 'Execute request via selected provider' },
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Route className="size-4 text-primary" />
          Routing Pipeline
        </CardTitle>
        <CardDescription>Flow diagram showing the active routing path for each request</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-0 overflow-x-auto pb-2">
          {pipelineSteps.map((step, idx) => (
            <div key={step.label} className="flex items-center gap-2 sm:gap-0">
              <div className={`flex flex-col items-center min-w-[100px] p-2 rounded-lg border transition-all ${
                step.active ? 'border-primary/30 bg-primary/5' : 'border-border/50 bg-muted/30 opacity-50'
              }`}>
                <CircleDot className={`size-4 mb-1 ${step.active ? 'text-primary' : 'text-muted-foreground'}`} />
                <span className={`text-[10px] font-semibold whitespace-nowrap ${step.active ? 'text-foreground' : 'text-muted-foreground'}`}>
                  {step.label}
                </span>
                <span className="text-[8px] text-muted-foreground text-center leading-tight mt-0.5 max-w-[90px]">
                  {step.desc}
                </span>
              </div>
              {idx < pipelineSteps.length - 1 && (
                <ArrowRight className="size-4 text-muted-foreground/40 shrink-0 mx-1 hidden sm:block" />
              )}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-border">
          <Badge variant="outline" className="text-[10px] gap-1"><Zap className="size-3" /> Strategy: {strategy}</Badge>
          <Badge variant="outline" className="text-[10px] gap-1"><Shield className="size-3" /> Sticky: {stickyEnabled ? 'ON' : 'OFF'}</Badge>
          <Badge variant="outline" className="text-[10px] gap-1"><GitBranch className="size-3" /> Affinity: {affinityEnabled ? 'ON' : 'OFF'}</Badge>
          <Badge variant="outline" className="text-[10px] gap-1"><Layers className="size-3" /> Tier Fallback: {tierFallback ? 'ON' : 'OFF'}</Badge>
        </div>
      </CardContent>
    </Card>
  )
}

function RoutingSandbox() {
  const [testModel, setTestModel] = useState('')
  const [testCapabilities, setTestCapabilities] = useState('')
  const [result, setResult] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleTest() {
    setLoading(true)
    setResult(null)
    try {
      const caps = testCapabilities.split(',').map((c) => c.trim()).filter(Boolean)
      const body: Record<string, unknown> = {}
      if (testModel) body.model = testModel
      if (caps.length > 0) body.capabilities = caps
      const data = await apiFetch<{
        selected_provider: string; selected_model: string; tier: number; key_id: number; reason: string
      }>('/api/settings/test-routing', {
        method: 'POST', body: JSON.stringify(body),
      })
      setResult(JSON.stringify(data, null, 2))
    } catch (err) {
      setResult(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Search className="size-4 text-primary" />
          Test Routing
        </CardTitle>
        <CardDescription>See what would happen if you sent a request with specific parameters</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Model (optional)</label>
            <Input placeholder="llama-3.3-70b-versatile" value={testModel}
              onChange={(e) => setTestModel(e.target.value)} className="h-9 text-xs font-mono" />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Capabilities (comma-separated)</label>
            <Input placeholder="general_purpose, fast" value={testCapabilities}
              onChange={(e) => setTestCapabilities(e.target.value)} className="h-9 text-xs font-mono" />
          </div>
        </div>
        <Button size="sm" onClick={handleTest} disabled={loading}>
          {loading ? <Loader2 className="size-3 animate-spin mr-1" /> : <Activity className="size-3 mr-1" />}
          Test Route
        </Button>
        {result && (
          <div className="mt-3 p-3 rounded-lg bg-muted font-mono text-[11px] whitespace-pre-wrap">{result}</div>
        )}
      </CardContent>
    </Card>
  )
}

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [strategy, setStrategy] = useState('balanced')
  const [customWeights, setCustomWeights] = useState({ reliability: 0.5, speed: 0.25, intelligence: 0.25 })
  const [stickyEnabled, setStickyEnabled] = useState(true)
  const [stickyTtlMs, setStickyTtlMs] = useState(600000)
  const [stickyMaxEntries, setStickyMaxEntries] = useState(1000)
  const [handoffMode, setHandoffMode] = useState('off')
  const [tierFallbackEnabled, setTierFallbackEnabled] = useState(true)
  const [qualityTier, setQualityTier] = useState(1)
  const [maxFallbackTier, setMaxFallbackTier] = useState(4)
  const [tierMin, setTierMin] = useState(1)
  const [tierMax, setTierMax] = useState(4)
  const [fallback, setFallback] = useState<FallbackConfig>({
    max_attempts_same_key: 3,
    max_attempts_same_provider: 3,
    max_attempts_all_providers: 3,
    cooldown_on_failure_ms: 1800000,
  })
  const [affinityEnabled, setAffinityEnabled] = useState(false)
  const [routeOverrideModels, setRouteOverrideModels] = useState('')

  const [slimeyEnabled, setSlimeyEnabled] = useState(false)
  const [slimeyMaxTTFT, setSlimeyMaxTTFT] = useState(2000)
  const [slimeyMinThroughput, setSlimeyMinThroughput] = useState(10)
  const [slimeyTierConfig, setSlimeyTierConfig] = useState(1)
  const [slimeyStrategy, setSlimeyStrategy] = useState('balanced')

  const [saveFeedback, setSaveFeedback] = useState<{ ok: boolean; msg: string } | null>(null)
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const showFeedback = (ok: boolean, msg: string) => {
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current)
    setSaveFeedback({ ok, msg })
    feedbackTimer.current = setTimeout(() => setSaveFeedback(null), 3000)
  }

  const { data: strData } = useQuery<{ strategy: string }>({ queryKey: ['routing-strategy'], queryFn: () => apiFetch('/api/settings/routing-strategy') })
  const { data: stkData } = useQuery<StickyConfig>({ queryKey: ['sticky'], queryFn: () => apiFetch('/api/settings/sticky') })
  const { data: hndData } = useQuery<{ mode: string }>({ queryKey: ['handoff'], queryFn: () => apiFetch('/api/settings/handoff') })
  const { data: fbData } = useQuery<FallbackConfig>({ queryKey: ['fallback-settings'], queryFn: () => apiFetch('/api/settings/fallback') })
  const { data: tfData } = useQuery<{ tier_fallback_enabled: boolean }>({ queryKey: ['tier-fallback'], queryFn: () => apiFetch('/api/settings/tier-fallback') })
  const { data: tierSettings } = useQuery<TierSettings>({ queryKey: ['tier-settings'], queryFn: () => apiFetch('/api/settings/tier-settings') })
  const { data: affData } = useQuery<AffinityConfig>({ queryKey: ['affinity'], queryFn: () => apiFetch('/api/settings/affinity') })
  const { data: roData } = useQuery<RoutingOverride>({ queryKey: ['routing-override'], queryFn: () => apiFetch('/api/settings/routing-override') })
  const { data: slimeyData } = useQuery<{ enabled: boolean; max_ttft_ms: number; min_throughput_rps: number; tier: number; strategy: string }>({
    queryKey: ['slimey-settings'], queryFn: () => apiFetch('/api/settings/slimey'), staleTime: 30_000,
  })

  useEffect(() => { if (strData?.strategy) setStrategy(strData.strategy) }, [strData])
  useEffect(() => { if (stkData) { setStickyEnabled(stkData.sticky_enabled); setStickyTtlMs(stkData.sticky_ttl_ms); setStickyMaxEntries(stkData.max_sticky_entries) } }, [stkData])
  useEffect(() => { if (hndData?.mode) setHandoffMode(hndData.mode) }, [hndData])
  useEffect(() => { if (tfData?.tier_fallback_enabled !== undefined) setTierFallbackEnabled(tfData.tier_fallback_enabled) }, [tfData])
  useEffect(() => { if (tierSettings) { setQualityTier(tierSettings.quality_tier); setMaxFallbackTier(tierSettings.max_fallback_tier); setTierMin(tierSettings.min_tier); setTierMax(tierSettings.max_tier) } }, [tierSettings])
  useEffect(() => { if (affData?.affinity_enabled !== undefined) setAffinityEnabled(affData.affinity_enabled) }, [affData])
  useEffect(() => { if (roData) setRouteOverrideModels(roData.models.join(', ')) }, [roData])
  useEffect(() => { if (fbData) setFallback(fbData) }, [fbData])
  useEffect(() => { if (slimeyData) { setSlimeyEnabled(slimeyData.enabled); setSlimeyMaxTTFT(slimeyData.max_ttft_ms); setSlimeyMinThroughput(slimeyData.min_throughput_rps); setSlimeyTierConfig(slimeyData.tier); setSlimeyStrategy(slimeyData.strategy) } }, [slimeyData])

  const saveAll = useMutation({
    mutationFn: async () => {
      const forcedModels = routeOverrideModels.split(',').map((m) => m.trim()).filter(Boolean)
      return apiFetch('/api/settings/save-all', {
        method: 'POST',
        body: JSON.stringify({
          strategy,
          custom_weights: strategy === 'custom' ? customWeights : undefined,
          sticky_enabled: stickyEnabled,
          sticky_ttl_ms: stickyTtlMs,
          max_sticky_entries: stickyMaxEntries,
          handoff_mode: handoffMode,
          tier_fallback_enabled: tierFallbackEnabled,
          quality_tier: qualityTier,
          max_fallback_tier: maxFallbackTier,
          affinity_enabled: affinityEnabled,
          fallback,
          forced_models: forcedModels.length > 0 ? forcedModels : [],
          slimey: { enabled: slimeyEnabled, max_ttft_ms: slimeyMaxTTFT, min_throughput_rps: slimeyMinThroughput, tier: slimeyTierConfig, strategy: slimeyStrategy },
        }),
      })
    },
    onSuccess: () => { showFeedback(true, 'All settings saved'); queryClient.invalidateQueries() },
    onError: (err: Error) => { showFeedback(false, err.message || 'Failed to save settings') },
  })

  return (
    <div>
      <PageHeader title="Settings" description="Configure routing strategy, session behavior, fallback modes, and everything else" />

      <div className="space-y-6 max-w-3xl">
        <RoutingPipelineCard />
        <RoutingSandbox />

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><PieChart className="size-4 text-primary" /> Routing Strategy <HelpNode content={HELP.routingStrategy} side="right" /></CardTitle>
            <CardDescription>How the pool selects the best model for each request</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {STRATEGIES.map((s) => (
                <button key={s} onClick={() => setStrategy(s)}
                  className={`px-3 py-1.5 rounded-md text-sm capitalize transition-colors ${
                    strategy === s ? 'bg-primary text-primary-foreground font-medium' : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'
                  }`}>{s}</button>
              ))}
            </div>
          </CardContent>
        </Card>

        {strategy === 'custom' && (
          <Card>
            <CardHeader><CardTitle>Custom Weights <HelpNode content={HELP.customWeights} /></CardTitle><CardDescription>Fine-tune the routing scoring weights</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              {(['reliability', 'speed', 'intelligence'] as const).map((axis) => (
                <div key={axis} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="capitalize text-muted-foreground">{axis}</span>
                    <span className="tabular-nums">{customWeights[axis].toFixed(2)}</span>
                  </div>
                  <input type="range" min="0" max="1" step="0.05" value={customWeights[axis]}
                    onChange={(e) => setCustomWeights((w) => ({ ...w, [axis]: parseFloat(e.target.value) }))}
                    className="w-full accent-primary" />
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        <CollapsibleSection title="Fallback Chain" description="Configure retry behavior when keys fail"
          icon={<Layers className="size-4 text-amber-500" />} defaultOpen>
          <div className="space-y-4">
            <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 text-xs text-muted-foreground">
              <strong className="text-amber-600">How it works:</strong> When a key fails (429, timeout, error),
              the fallback chain tries the next key, then the next provider, then the next tier.
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Attempts (same key) <HelpNode content={HELP.fallbackMaxSameKey} side="right" /></label>
                <Input type="number" min={1} max={20} value={fallback.max_attempts_same_key}
                  onChange={(e) => setFallback({ ...fallback, max_attempts_same_key: parseInt(e.target.value) || 3 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Attempts (same provider) <HelpNode content={HELP.fallbackMaxSameProvider} side="right" /></label>
                <Input type="number" min={1} max={20} value={fallback.max_attempts_same_provider}
                  onChange={(e) => setFallback({ ...fallback, max_attempts_same_provider: parseInt(e.target.value) || 3 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Attempts (all providers) <HelpNode content={HELP.fallbackMaxAllProviders} side="right" /></label>
                <Input type="number" min={1} max={20} value={fallback.max_attempts_all_providers}
                  onChange={(e) => setFallback({ ...fallback, max_attempts_all_providers: parseInt(e.target.value) || 3 })} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Cooldown on failure (ms) <HelpNode content={HELP.fallbackCooldown} side="right" /></label>
                <Input type="number" min={0} step={60000} value={fallback.cooldown_on_failure_ms}
                  onChange={(e) => setFallback({ ...fallback, cooldown_on_failure_ms: parseInt(e.target.value) || 1800000 })} />
              </div>
            </div>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title="Sticky Sessions" description="Route consecutive requests from the same session to the same model+key"
          icon={<Shield className="size-4 text-blue-500" />} defaultOpen>
          <div className="space-y-4">
            <div className="rounded-lg bg-blue-500/5 border border-blue-500/20 p-3 text-xs text-muted-foreground">
              <strong className="text-blue-600">How it works:</strong> Once a session is assigned to a key+model pair,
              all subsequent requests use the same pair until TTL expiry.
            </div>
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium">Enable Sticky Sessions <HelpNode content={HELP.stickyEnabled} side="top" /></h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {stkData?.active_sessions !== undefined ? `${stkData.active_sessions} active session(s)` : '—'}
                </p>
              </div>
              <Switch checked={stickyEnabled} onCheckedChange={setStickyEnabled} />
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">TTL (ms) <HelpNode content={HELP.stickyTtl} side="right" /></label>
                <Input type="number" min={1000} step={10000} value={stickyTtlMs}
                  onChange={(e) => setStickyTtlMs(parseInt(e.target.value) || 600000)} />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Max Entries <HelpNode content={HELP.stickyMaxEntries} side="right" /></label>
                <Input type="number" min={1} max={100000} value={stickyMaxEntries}
                  onChange={(e) => setStickyMaxEntries(parseInt(e.target.value) || 1000)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Tier Config</label>
                <select value={qualityTier} onChange={(e) => setQualityTier(parseInt(e.target.value))}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm">
                  {[1, 2, 3, 4].map((t) => (<option key={t} value={t}>Tier {t}</option>))}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Strategy</label>
                <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm">
                  {STRATEGIES.map((s) => (<option key={s} value={s}>{s}</option>))}
                </select>
              </div>
            </div>
          </div>
        </CollapsibleSection>

        <CollapsibleSection title="Slimey Mode" description="Latency-optimized routing — prefers the fastest available model"
          icon={<Gauge className="size-4 text-emerald-500" />}>
          <div className="space-y-4">
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3 text-xs text-muted-foreground">
              <strong className="text-emerald-600">How it works:</strong> Slimey mode prioritizes low time-to-first-token
              and high throughput. Routes to the fastest option meeting your quality requirements.
            </div>
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium">Enable Slimey Mode <HelpNode content={HELP.fallbackModeSlimey} side="top" /></h3>
                <p className="text-xs text-muted-foreground mt-0.5">Routes based on real-time latency and throughput</p>
              </div>
              <Switch checked={slimeyEnabled} onCheckedChange={setSlimeyEnabled} />
            </div>
            {slimeyEnabled && (
              <div className="space-y-4 pt-2">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <Timer className="size-3" /> Max TTFT: <span className="text-foreground font-medium">{slimeyMaxTTFT}ms</span>
                    <HelpNode content={HELP.slimeyMaxTtft} side="right" />
                  </label>
                  <input type="range" min={100} max={10000} step={100} value={slimeyMaxTTFT}
                    onChange={(e) => setSlimeyMaxTTFT(parseInt(e.target.value))} className="w-full accent-primary" />
                  <div className="flex justify-between text-[10px] text-muted-foreground"><span>100ms</span><span>10s</span></div>
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <Gauge className="size-3" /> Min Throughput: <span className="text-foreground font-medium">{slimeyMinThroughput} req/s</span>
                    <HelpNode content={HELP.slimeyMinThroughput} side="right" />
                  </label>
                  <input type="range" min={1} max={100} step={1} value={slimeyMinThroughput}
                    onChange={(e) => setSlimeyMinThroughput(parseInt(e.target.value))} className="w-full accent-primary" />
                  <div className="flex justify-between text-[10px] text-muted-foreground"><span>1 req/s</span><span>100 req/s</span></div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Tier Config</label>
                    <select value={slimeyTierConfig} onChange={(e) => setSlimeyTierConfig(parseInt(e.target.value))}
                      className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm">
                      {[1, 2, 3, 4].map((t) => (<option key={t} value={t}>Tier {t}</option>))}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">Strategy</label>
                    <select value={slimeyStrategy} onChange={(e) => setSlimeyStrategy(e.target.value)}
                      className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm">
                      {STRATEGIES.map((s) => (<option key={s} value={s}>{s}</option>))}
                    </select>
                  </div>
                </div>
              </div>
            )}
          </div>
        </CollapsibleSection>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><GitBranch className="size-4 text-purple-500" /> Affinity Routing <HelpNode content={HELP.affinityEnabled} side="right" /></CardTitle>
            <CardDescription>Pin UIDs to key+model pairs with 5-slot concurrency. Mutually exclusive with sticky sessions.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium">Enable Affinity Routing</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {affData ? `${affData.busy.length} busy, ${affData.semi_busy.length} semi-busy, ${affData.available_slots}/${affData.total_slots} slots free, ${affData.pinned_uids} UIDs` : '—'}
                </p>
              </div>
              <Switch checked={affinityEnabled} onCheckedChange={(val) => { setAffinityEnabled(val); if (val) setStickyEnabled(false) }} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Activity className="size-4 text-cyan-500" /> Context Handoff <HelpNode content={HELP.handoffMode} side="right" /></CardTitle>
            <CardDescription>Preserve conversation context when switching between models</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium">Handoff Mode</h3>
                <p className="text-xs text-muted-foreground mt-0.5">When enabled, a summary of the prior conversation is injected into the new model</p>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setHandoffMode('off')}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${handoffMode === 'off' ? 'bg-primary text-primary-foreground font-medium' : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'}`}>
                  Off
                </button>
                <button onClick={() => setHandoffMode('on_model_switch')}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${handoffMode === 'on_model_switch' ? 'bg-primary text-primary-foreground font-medium' : 'bg-secondary text-secondary-foreground hover:bg-secondary/80'}`}>
                  On Model Switch
                </button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Layers className="size-4 text-orange-500" /> Tier Fallback <HelpNode content={HELP.tierFallbackEnabled} side="right" /></CardTitle>
            <CardDescription>Control how the pool falls back through model quality tiers</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium">Enable Tier Fallback</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Automatically fall back when higher-tier keys are exhausted</p>
              </div>
              <Switch checked={tierFallbackEnabled} onCheckedChange={setTierFallbackEnabled} />
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Quality Tier: <span className="text-foreground font-medium">{qualityTier}</span> <HelpNode content={HELP.qualityTier} side="right" /></label>
                <input type="range" min={tierMin} max={tierMax} step={1} value={qualityTier}
                  onChange={(e) => { const v = parseInt(e.target.value); setQualityTier(v); if (v > maxFallbackTier) setMaxFallbackTier(v) }}
                  className="w-full accent-primary" />
                <div className="flex justify-between text-[10px] text-muted-foreground"><span>Tier 1 (Best)</span><span>Tier {tierMax}</span></div>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Max Fallback Tier: <span className="text-foreground font-medium">{maxFallbackTier}</span> <HelpNode content={HELP.maxFallbackTier} side="right" /></label>
                <input type="range" min={qualityTier} max={tierMax} step={1} value={maxFallbackTier}
                  onChange={(e) => setMaxFallbackTier(parseInt(e.target.value))} className="w-full accent-primary" />
                <div className="flex justify-between text-[10px] text-muted-foreground"><span>Same tier</span><span>Tier {tierMax}</span></div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Zap className="size-4 text-amber-500" /> Routing Override <HelpNode content={HELP.routingOverride} side="right" /></CardTitle>
            <CardDescription>Temporarily restrict routing to specific model(s). Empty = normal routing.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Comma-separated model names</label>
              <Input type="text" placeholder="llama-3.3-70b-versatile, gemini-2.0-flash" value={routeOverrideModels}
                onChange={(e) => setRouteOverrideModels(e.target.value)} />
              {roData?.override_active && <p className="text-xs text-amber-500 mt-1">Override active — routing is restricted to specified models only</p>}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="sticky bottom-6 mt-8 flex items-center justify-center gap-3 z-10">
        {saveFeedback && (
          <span className={`flex items-center gap-1.5 text-sm font-medium ${saveFeedback.ok ? 'text-emerald-500' : 'text-red-500'}`}>
            {saveFeedback.ok ? <CheckCircle2 className="size-4" /> : <AlertCircle className="size-4" />}
            {saveFeedback.msg}
            <button onClick={() => setSaveFeedback(null)} className="ml-1 hover:opacity-70"><X className="size-3" /></button>
          </span>
        )}
        <Button size="lg" onClick={() => saveAll.mutate()} disabled={saveAll.isPending} className="shadow-lg">
          {saveAll.isPending ? <Loader2 className="size-5 animate-spin mr-2" /> : <Save className="size-5 mr-2" />}
          {saveAll.isPending ? 'Saving\u2026' : 'Save All Settings'}
        </Button>
      </div>
    </div>
  )
}
