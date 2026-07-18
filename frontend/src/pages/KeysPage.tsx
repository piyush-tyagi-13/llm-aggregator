import { useState, useMemo, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import {
  Plus, Trash2, Loader2, Upload, CheckCircle2, AlertCircle,
  HelpCircle, Search, X, ChevronDown, ChevronRight, Copy,
  Check, Settings2, Globe, ExternalLink, Pin, PinOff, RefreshCw,
  Activity, Zap, Timer, AlertTriangle, Filter, Key,
} from 'lucide-react'

interface Key {
  id: number
  provider: string
  api_key?: string
  model: string | null
  is_active: number
  requests_today: number
  cooldown_until: string | null
  context_size: number | null
  accuracy_score: number
  speed_score: number
  reliability_score: number
  group_name: string
}

interface ModelRow {
  id: number
  platform: string
  model_id: string
  display_name: string
  tier: number
  enabled: boolean
  context_window: number | null
  supports_vision: boolean
  supports_tools: boolean
  is_free: boolean
  supports_streaming: boolean
}

import { HelpNode } from '@/components/ui/help-node'
import { HELP } from '@/lib/help-text'

interface AutoResult { key: string; candidates: string[]; status: string }
interface ProbingResult { key: string; candidates: string[]; probed: { provider: string; success: boolean; detail: string }[]; status: string; detected_provider: string | null }
interface ImportAnalysis { keys: { auto: AutoResult[]; probed: ProbingResult[]; unknown: AutoResult[]; skipped: AutoResult[] }; summary: { total: number; auto: number; confirmed: number; ambiguous: number; unknown: number } }
interface ImportEntry { key: string; provider: string; base_url_override: string | null; model: string | null; capabilities: string[] | null }

function MockSparkline({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(...values, 1)
  return (
    <div className="flex items-end gap-[2px] h-6">
      {values.map((v, i) => (
        <div key={i} className="w-1.5 rounded-t-sm transition-all duration-300"
          style={{ height: `${(v / max) * 100}%`, backgroundColor: color, opacity: 0.4 + (v / max) * 0.6 }} />
      ))}
    </div>
  )
}

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-border overflow-hidden">
      <div className="p-4"><div className="skeleton h-5 w-32 mb-2" /><div className="skeleton h-3 w-48" /></div>
      <div className="border-t border-border p-4 space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="skeleton size-2 rounded-full" />
            <div className="skeleton h-4 flex-1" />
            <div className="skeleton size-8 rounded" />
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      <div className="size-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
        <Key className="size-8 text-primary" />
      </div>
      <h3 className="text-lg font-semibold text-foreground mb-1">No API Keys Yet</h3>
      <p className="text-sm text-muted-foreground text-center max-w-sm mb-6">
        Add your first provider API key to start routing requests through the pool.
      </p>
      <div className="flex gap-3">
        <Button onClick={onAdd}><Plus className="size-4 mr-1" /> Add Key</Button>
      </div>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      <div className="size-16 rounded-2xl bg-destructive/10 flex items-center justify-center mb-4">
        <AlertCircle className="size-8 text-destructive" />
      </div>
      <h3 className="text-lg font-semibold text-foreground mb-1">Failed to Load Keys</h3>
      <p className="text-sm text-muted-foreground text-center max-w-sm mb-6">{message}</p>
      <Button variant="outline" onClick={onRetry}><RefreshCw className="size-4 mr-1" /> Retry</Button>
    </div>
  )
}

export function KeysPage() {
  const queryClient = useQueryClient()
  const [showAddForm, setShowAddForm] = useState(false)
  const [newKey, setNewKey] = useState({ provider: '', api_key: '', model: '', group_name: 'default' })
  const [showBulkImport, setShowBulkImport] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [analysis, setAnalysis] = useState<ImportAnalysis | null>(null)
  const [manualOverrides, setManualOverrides] = useState<Record<string, { provider: string; baseUrl: string }>>({})
  const [providerModal, setProviderModal] = useState<string | null>(null)
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set())
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [providerFilter, setProviderFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive' | 'cooldown'>('all')
  const [selectedKeys, setSelectedKeys] = useState<Set<number>>(new Set())
  const [selectMode, setSelectMode] = useState(false)

  const { data: keys = [], isLoading, isError, error, refetch } = useQuery<Key[]>({
    queryKey: ['keys'],
    queryFn: () => apiFetch('/api/keys'),
  })

  const { data: allModels } = useQuery<ModelRow[]>({
    queryKey: ['api-models'], queryFn: () => apiFetch('/api/models'), staleTime: 30_000,
  })

  const { data: providersData } = useQuery<{ providers: string[] }>({
    queryKey: ['providers'], queryFn: () => apiFetch('/api/providers'),
  })

  const { data: routingOverride } = useQuery<{ models: string[]; override_active: boolean }>({
    queryKey: ['routing-override'], queryFn: () => apiFetch('/api/settings/routing-override'), staleTime: 5_000,
  })

  const addKey = useMutation({
    mutationFn: (body: { provider: string; api_key: string; model?: string; group_name?: string; capabilities?: string[] }) =>
      apiFetch('/api/keys', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['keys'] }); setShowAddForm(false); setNewKey({ provider: '', api_key: '', model: '', group_name: 'default' }) },
  })

  const toggleActive = useMutation({
    mutationFn: ({ id, isActive }: { id: number; isActive: boolean }) =>
      apiFetch(`/api/keys/${id}/${isActive ? 'deactivate' : 'activate'}`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys'] }),
  })

  const deleteKey = useMutation({
    mutationFn: (id: number) => apiFetch(`/api/keys/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys'] }),
  })

  const clearCooldown = useMutation({
    mutationFn: (id: number) => apiFetch(`/api/keys/${id}/clear-cooldown`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys'] }),
  })

  const [editingKeyModel, setEditingKeyModel] = useState<{ id: number; model: string } | null>(null)

  const updateKeyModel = useMutation({
    mutationFn: ({ id, model }: { id: number; model: string }) =>
      apiFetch(`/api/keys/${id}`, { method: 'PATCH', body: JSON.stringify({ model: model || null }) }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['keys'] }); setEditingKeyModel(null) },
  })

  const batchMutation = useMutation({
    mutationFn: ({ ids, action }: { ids: number[]; action: 'activate' | 'deactivate' | 'delete' }) =>
      apiFetch('/api/keys/batch', { method: 'POST', body: JSON.stringify({ ids, action }) }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['keys'] }); setSelectedKeys(new Set()); setSelectMode(false) },
  })

  const analyseMutation = useMutation({
    mutationFn: (text: string) => apiFetch<ImportAnalysis>('/api/keys/auto-import', { method: 'POST', body: JSON.stringify({ text }) }),
    onSuccess: (data: ImportAnalysis) => {
      setAnalysis(data)
      const overrides: Record<string, { provider: string; baseUrl: string }> = {}
      for (const k of data.keys.unknown) overrides[k.key] = { provider: '', baseUrl: '' }
      for (const k of data.keys.probed) { if (k.status === 'unknown') overrides[k.key] = { provider: '', baseUrl: '' } }
      setManualOverrides(overrides)
    },
  })

  const commitMutation = useMutation({
    mutationFn: (entries: ImportEntry[]) =>
      apiFetch<{ imported: number; errors: { key: string; error: string }[] }>('/api/keys/commit-import', { method: 'POST', body: JSON.stringify({ keys: entries }) }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['keys'] })
      if (data.errors.length === 0) { setShowBulkImport(false); setBulkText(''); setAnalysis(null); setManualOverrides({}) }
    },
  })

  const isKeyHealthy = (key: Key) => {
    if (!key.is_active) return false
    if (key.cooldown_until && key.cooldown_until > new Date().toISOString()) return false
    return true
  }

  const providers = providersData?.providers ?? []

  const buildCommitEntries = (): ImportEntry[] => {
    if (!analysis) return []
    const entries: ImportEntry[] = []
    for (const k of analysis.keys.auto) entries.push({ key: k.key, provider: k.candidates[0], base_url_override: null, model: null, capabilities: ['general_purpose'] })
    for (const k of analysis.keys.probed) {
      if (k.status === 'confirmed') entries.push({ key: k.key, provider: k.detected_provider!, base_url_override: null, model: null, capabilities: ['general_purpose'] })
      else if (k.status === 'ambiguous') { const passing = k.probed.find((p) => p.success); if (passing) entries.push({ key: k.key, provider: passing.provider, base_url_override: null, model: null, capabilities: ['general_purpose'] }) }
    }
    for (const [key, override] of Object.entries(manualOverrides)) { if (override.provider) entries.push({ key, provider: override.provider, base_url_override: override.baseUrl || null, model: null, capabilities: ['general_purpose'] }) }
    return entries
  }

  const commitEntries = buildCommitEntries()
  const entriesWithoutProvider = Object.entries(manualOverrides).filter(([, v]) => !v.provider).length
  const canCommit = commitEntries.length > 0 && entriesWithoutProvider === 0

  const groupedKeys = useMemo(() => {
    const map = new Map<string, Key[]>()
    for (const key of keys) { const list = map.get(key.provider) || []; list.push(key); map.set(key.provider, list) }
    return map
  }, [keys])

  const providerNames = useMemo(() => {
    let names = Array.from(groupedKeys.keys()).sort()
    if (providerFilter) names = names.filter((n) => n.toLowerCase().includes(providerFilter.toLowerCase()))
    return names
  }, [groupedKeys, providerFilter])

  const filteredKeys = useMemo(() => {
    if (!searchQuery && statusFilter === 'all') return keys
    const q = searchQuery.toLowerCase()
    return keys.filter((k) => {
      if (statusFilter === 'active' && !k.is_active) return false
      if (statusFilter === 'inactive' && k.is_active) return false
      if (statusFilter === 'cooldown' && !(k.cooldown_until && k.cooldown_until > new Date().toISOString())) return false
      if (q) {
        const matchProvider = k.provider.toLowerCase().includes(q)
        const matchKey = k.api_key?.toLowerCase().includes(q) ?? false
        const matchModel = k.model?.toLowerCase().includes(q) ?? false
        if (!matchProvider && !matchKey && !matchModel) return false
      }
      return true
    })
  }, [keys, searchQuery, statusFilter])

  const copyToClipboard = useCallback(async (text: string, key: string) => {
    try { await navigator.clipboard.writeText(text) } catch {
      const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta)
    }
    setCopiedKey(key); setTimeout(() => setCopiedKey(null), 2000)
  }, [])

  const toggleProviderExpanded = useCallback((provider: string) => {
    setExpandedProviders((prev) => { const next = new Set(prev); if (next.has(provider)) next.delete(provider); else next.add(provider); return next })
  }, [])

  const toggleSelectKey = (id: number) => {
    setSelectedKeys((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
  }

  const toggleSelectAll = () => {
    if (selectedKeys.size === filteredKeys.length) setSelectedKeys(new Set())
    else setSelectedKeys(new Set(filteredKeys.map((k) => k.id)))
  }

  const maskKey = (k: string) => {
    if (k.length <= 8) return k
    return k.slice(0, 6) + '\u2026' + k.slice(-4)
  }

  if (isLoading) {
    return (
      <div>
        <PageHeader title="API Keys" description="Manage provider keys" />
        <div className="space-y-4">{[1, 2, 3].map((i) => <SkeletonCard key={i} />)}</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div>
        <PageHeader title="API Keys" description="Manage provider keys" />
        <ErrorState message={error?.message ?? 'Unknown error'} onRetry={() => refetch()} />
      </div>
    )
  }

  if (keys.length === 0 && !showAddForm) {
    return (
      <div>
        <PageHeader title="API Keys" description="Manage provider keys" />
        <EmptyState onAdd={() => setShowAddForm(true)} />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="API Keys"
        description="Manage provider keys — grouped by provider for quick access"
        actions={
          <div className="flex gap-2">
            {selectMode && selectedKeys.size > 0 && (
              <>
                <Button size="sm" variant="outline" onClick={() => batchMutation.mutate({ ids: Array.from(selectedKeys), action: 'activate' })} disabled={batchMutation.isPending}>
                  <CheckCircle2 className="size-3 mr-1" /> Activate ({selectedKeys.size})
                </Button>
                <Button size="sm" variant="outline" onClick={() => batchMutation.mutate({ ids: Array.from(selectedKeys), action: 'deactivate' })} disabled={batchMutation.isPending}>
                  <X className="size-3 mr-1" /> Deactivate
                </Button>
                <Button size="sm" variant="destructive" onClick={() => { if (confirm(`Delete ${selectedKeys.size} keys?`)) batchMutation.mutate({ ids: Array.from(selectedKeys), action: 'delete' }) }} disabled={batchMutation.isPending}>
                  <Trash2 className="size-3 mr-1" /> Delete
                </Button>
              </>
            )}
            <Button size="sm" variant={selectMode ? 'default' : 'outline'} onClick={() => { setSelectMode(!selectMode); setSelectedKeys(new Set()) }}>
              <Filter className="size-3 mr-1" /> {selectMode ? 'Exit Select' : 'Bulk Select'}
            </Button>
<Button size="sm" variant="outline" onClick={() => setShowBulkImport(true)}>
               <Upload className="size-4 mr-1" /> Bulk Import <HelpNode content={HELP.bulkImport} side="top" />
             </Button>
            <Button size="sm" onClick={() => setShowAddForm(true)}>
              <Plus className="size-4 mr-1" /> Add Key
            </Button>
          </div>
        }
      />

      {/* Search & Filter Bar */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input placeholder="Search by key prefix, provider, model..." value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)} className="pl-10 h-9 text-sm" />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="size-3.5" />
            </button>
          )}
        </div>
        <select value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
          <option value="">All Providers</option>
          {providers.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
          <option value="all">All Status</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="cooldown">Cooldown</option>
        </select>
        <span className="text-xs text-muted-foreground">{filteredKeys.length} of {keys.length} keys</span>
      </div>

      {/* Bulk Import Modal */}
      {showBulkImport && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-12 pb-8 overflow-y-auto">
          <div className="fixed inset-0 bg-black/50" onClick={() => setShowBulkImport(false)} />
          <div className="relative bg-background border border-border rounded-xl shadow-2xl w-full max-w-3xl mx-4 z-10 animate-scale-in">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <div>
                <h2 className="text-base font-semibold">Bulk Import API Keys</h2>
                <p className="text-xs text-muted-foreground mt-0.5">Paste keys (one per line). Auto-detected formats.</p>
              </div>
              <button onClick={() => { setShowBulkImport(false); setAnalysis(null); setBulkText('') }} className="text-muted-foreground hover:text-foreground"><X className="size-5" /></button>
            </div>
            <div className="p-5 space-y-4">
              {!analysis && (
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Paste your API keys here:</Label>
                  <Textarea placeholder={"sk-sdoi***\nMzZic+bpL0xSBs***\nAIzaSy..."} value={bulkText}
                    onChange={(e) => setBulkText(e.target.value)} className="min-h-[160px] font-mono text-xs" />
                  <div className="flex justify-end">
                    <Button size="sm" onClick={() => analyseMutation.mutate(bulkText)} disabled={!bulkText.trim() || analyseMutation.isPending}>
                      {analyseMutation.isPending ? <Loader2 className="size-4 animate-spin mr-1" /> : <Search className="size-4 mr-1" />}
                      Analyse & Identify
                    </Button>
                  </div>
                </div>
              )}
              {analysis && (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-3 text-xs">
                    <span className="flex items-center gap-1 text-emerald-600"><CheckCircle2 className="size-3.5" /> {analysis.summary.auto + analysis.summary.confirmed} auto-detected</span>
                    {analysis.summary.ambiguous > 0 && <span className="flex items-center gap-1 text-amber-600"><HelpCircle className="size-3.5" /> {analysis.summary.ambiguous} ambiguous</span>}
                    {analysis.summary.unknown > 0 && <span className="flex items-center gap-1 text-rose-600"><AlertCircle className="size-3.5" /> {analysis.summary.unknown} unknown</span>}
                    <span className="text-muted-foreground">{analysis.summary.total} total keys</span>
                  </div>
                  {analysis.keys.auto.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-emerald-600 mb-2 flex items-center gap-1"><CheckCircle2 className="size-3.5" /> Auto-detected ({analysis.keys.auto.length})</h4>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {analysis.keys.auto.map((k) => (
                          <div key={k.key} className="flex items-center gap-2 text-xs bg-muted/30 rounded px-3 py-1.5">
                            <span className="font-mono text-[11px] flex-1 truncate">{k.key.slice(0, 20)}\u2026</span>
                            <Badge variant="outline" className="text-[10px] font-mono">{k.candidates[0]}</Badge>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {analysis.keys.probed.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-amber-600 mb-2 flex items-center gap-1"><Search className="size-3.5" /> Tested against providers ({analysis.keys.probed.length})</h4>
                      <div className="space-y-2 max-h-48 overflow-y-auto">
                        {analysis.keys.probed.map((k) => {
                          const isResolved = k.status === 'confirmed'
                          return (
                            <div key={k.key} className="border rounded-lg p-3 text-xs space-y-2">
                              <div className="flex items-center justify-between">
                                <span className="font-mono text-[11px]">{k.key.slice(0, 24)}\u2026</span>
                                {isResolved ? <Badge className="text-[10px] bg-emerald-500/10 text-emerald-600 border-emerald-500/20">{k.detected_provider}</Badge> :
                                  <Badge variant="outline" className="text-[10px] text-amber-600">{k.status === 'ambiguous' ? 'Multiple matched' : 'No match'}</Badge>}
                              </div>
                              <div className="flex flex-wrap gap-1">
                                {k.probed.map((p) => (
                                  <span key={p.provider} className={`text-[10px] px-1.5 py-0.5 rounded ${p.success ? 'bg-emerald-500/10 text-emerald-600' : 'bg-muted text-muted-foreground'}`}>{p.provider}</span>
                                ))}
                              </div>
                              {!isResolved && (
                                <div className="flex gap-2 pt-1">
                                  <Select value={manualOverrides[k.key]?.provider || ''} onChange={(e) => setManualOverrides((o) => ({ ...o, [k.key]: { ...o[k.key], provider: e.target.value } }))} className="h-7 text-[11px] flex-1">
                                    <option value="">Select provider\u2026</option>
                                    {providers.map((p) => <option key={p} value={p}>{p}</option>)}
                                  </Select>
                                  <Input placeholder="base_url (optional)" value={manualOverrides[k.key]?.baseUrl || ''}
                                    onChange={(e) => setManualOverrides((o) => ({ ...o, [k.key]: { ...o[k.key], baseUrl: e.target.value } }))} className="h-7 text-[11px] font-mono flex-1" />
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                  {analysis.keys.unknown.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-rose-600 mb-2 flex items-center gap-1"><AlertCircle className="size-3.5" /> Unknown format ({analysis.keys.unknown.length})</h4>
                      <div className="space-y-2 max-h-48 overflow-y-auto">
                        {analysis.keys.unknown.map((k) => (
                          <div key={k.key} className="border border-rose-500/20 rounded-lg p-3 space-y-2">
                            <span className="font-mono text-[11px]">{k.key.slice(0, 24)}\u2026</span>
                            <div className="flex gap-2">
                              <Select value={manualOverrides[k.key]?.provider || ''} onChange={(e) => setManualOverrides((o) => ({ ...o, [k.key]: { ...o[k.key], provider: e.target.value } }))} className="h-7 text-[11px] flex-1">
                                <option value="">Select provider\u2026</option>
                                {providers.map((p) => <option key={p} value={p}>{p}</option>)}
                              </Select>
                              <Input placeholder="base_url (optional)" value={manualOverrides[k.key]?.baseUrl || ''}
                                onChange={(e) => setManualOverrides((o) => ({ ...o, [k.key]: { ...o[k.key], baseUrl: e.target.value } }))} className="h-7 text-[11px] font-mono flex-1" />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex items-center justify-between gap-3 pt-2 border-t">
                    <div className="text-xs text-muted-foreground">{commitEntries.length} keys ready to import{entriesWithoutProvider > 0 && <span className="text-amber-600 ml-1">({entriesWithoutProvider} need provider)</span>}</div>
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => { setAnalysis(null); analyseMutation.reset() }}>Back</Button>
                      {commitMutation.data?.errors && commitMutation.data.errors.length > 0 && <div className="text-xs text-rose-600 max-w-xs truncate">{commitMutation.data.errors[0].error}</div>}
                      <Button size="sm" onClick={() => commitMutation.mutate(commitEntries)} disabled={!canCommit || commitMutation.isPending}>
                        {commitMutation.isPending ? <Loader2 className="size-4 animate-spin mr-1" /> : <CheckCircle2 className="size-4 mr-1" />}
                        Import {commitEntries.length > 0 ? `(${commitEntries.length})` : ''}
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Add Key Form */}
      {showAddForm && (
        <Card className="mb-6 animate-slide-down">
          <CardHeader>
            <CardTitle>Add New Key</CardTitle>
            <CardDescription>Add a provider API key to the pool</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Provider</Label>
                <Select value={newKey.provider} onChange={(e) => setNewKey({ ...newKey, provider: e.target.value })}>
                  <option value="">Select Provider</option>
                  {providers.map((p) => <option key={p} value={p}>{p}</option>)}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">API Key</Label>
                <Input type="password" placeholder="sk-..." value={newKey.api_key} onChange={(e) => setNewKey({ ...newKey, api_key: e.target.value })} className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Model (optional)</Label>
                <Input placeholder="llama-3.3-70b-versatile" value={newKey.model} onChange={(e) => setNewKey({ ...newKey, model: e.target.value })} className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Group</Label>
                <Input placeholder="default" value={newKey.group_name} onChange={(e) => setNewKey({ ...newKey, group_name: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-2 mt-4">
              <Button size="sm" onClick={() => addKey.mutate({ ...newKey, capabilities: ['general_purpose'] })} disabled={!newKey.provider || !newKey.api_key || addKey.isPending}>
                {addKey.isPending ? <Loader2 className="size-4 animate-spin mr-1" /> : null} Add Key
              </Button>
              <Button size="sm" variant="outline" onClick={() => setShowAddForm(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Provider Grouped Key List */}
      <div className="space-y-4 animate-fade-in-up" data-stagger>
        {providerNames.map((provider) => {
          const providerKeys = groupedKeys.get(provider)!
          const activeKeys = providerKeys.filter((k) => k.is_active && isKeyHealthy(k))
          const cooldownKeys = providerKeys.filter((k) => k.cooldown_until && k.cooldown_until > new Date().toISOString())
          const isExpanded = expandedProviders.has(provider)
          const totalRequests = providerKeys.reduce((s, k) => s + k.requests_today, 0)
          const sparkValues = providerKeys.slice(0, 8).map((k) => k.speed_score || Math.random() * 100)

          return (
            <Card key={provider} className="overflow-hidden border-border/80 card-hover-dramatic">
              <div className={`h-1 ${activeKeys.length > 0 ? 'bg-emerald-500' : cooldownKeys.length > 0 ? 'bg-amber-500' : 'bg-muted-foreground/30'}`} />
              <div className="flex items-center gap-3 px-4 py-3 bg-card">
                <button onClick={() => toggleProviderExpanded(provider)} className="text-muted-foreground hover:text-foreground transition-colors shrink-0">
                  {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                </button>
                {selectMode && (
                  <input type="checkbox" checked={providerKeys.every((k) => selectedKeys.has(k.id))}
                    onChange={() => providerKeys.forEach((k) => toggleSelectKey(k.id))}
                    className="rounded border-border accent-primary" />
                )}
                <div className="flex-1 min-w-0">
                  <button onClick={() => setProviderModal(provider)}
                    className="text-base font-bold text-foreground hover:text-primary transition-colors text-left truncate flex items-center gap-2">
                    {provider} <ExternalLink className="size-3 text-muted-foreground" />
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <div className="hidden sm:flex items-end gap-1"><MockSparkline values={sparkValues} color="hsl(346, 75%, 52%)" /></div>
                  <span className="text-[10px] text-muted-foreground tabular-nums">{totalRequests} req</span>
                  {activeKeys.length > 0 && (
                    <Badge className="bg-emerald-500/10 text-emerald-600 border-emerald-500/25 text-[10px]">
                      <Zap className="size-3 mr-0.5" /> {activeKeys.length} active
                    </Badge>
                  )}
                  {cooldownKeys.length > 0 && (
                    <Badge className="bg-amber-500/10 text-amber-600 border-amber-500/25 text-[10px]">
                      <Timer className="size-3 mr-0.5" /> {cooldownKeys.length} cooling
                    </Badge>
                  )}
                  <Badge variant="outline" className="text-[10px]">{providerKeys.length} keys</Badge>
                  <Button variant="ghost" size="xs" onClick={() => setProviderModal(provider)} className="h-7 px-2 text-xs">
                    <Settings2 className="size-3 mr-1" /> Manage
                  </Button>
                </div>
              </div>

              {isExpanded && (
                <div className="border-t border-border/50 divide-y divide-border/30">
                  {providerKeys.map((key) => {
                    const isHealthy = isKeyHealthy(key)
                    const isOnCooldown = key.cooldown_until && key.cooldown_until > new Date().toISOString()
                    return (
                      <div key={key.id} className="flex items-center gap-3 px-4 py-3 pl-12 hover:bg-muted/30 transition-colors group">
                        {selectMode && (
                          <input type="checkbox" checked={selectedKeys.has(key.id)}
                            onChange={() => toggleSelectKey(key.id)}
                            className="rounded border-border accent-primary shrink-0" />
                        )}
                        <div className="relative shrink-0" data-testid="status-indicator">
                          <span className={`block size-2.5 rounded-full ${
                            key.is_active ? (isHealthy ? 'bg-emerald-500' : isOnCooldown ? 'bg-amber-500' : 'bg-red-500') : 'bg-muted-foreground/30'
                          }`} />
                          <HelpNode content={HELP.keyStatus} side="top" />
                          {isHealthy && <span className="absolute inset-0 size-2.5 rounded-full bg-emerald-500/30 animate-pulse" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-medium text-foreground/80 truncate">
                              {key.api_key ? maskKey(key.api_key) : `Key #${key.id}`}
                            </span>
                            {editingKeyModel?.id === key.id ? (
                              <input autoFocus type="text" className="w-40 text-[10px] font-mono px-1 py-0.5 rounded border border-border bg-background outline-none ring-1 ring-primary/30"
                                value={editingKeyModel.model}
                                onChange={(e) => setEditingKeyModel({ id: key.id, model: e.target.value })}
                                onBlur={() => { if (editingKeyModel && editingKeyModel.model !== (key.model || '')) updateKeyModel.mutate({ id: key.id, model: editingKeyModel.model }); else setEditingKeyModel(null) }}
                                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setEditingKeyModel(null) }} />
                            ) : (
                              <span className="text-[9px] px-1 py-0 font-mono rounded border border-transparent hover:border-border cursor-pointer transition-colors text-muted-foreground"
                                onClick={() => setEditingKeyModel({ id: key.id, model: key.model || '' })} title="Click to change model">
                                {key.model || 'default'}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-muted-foreground mt-0.5">
                            <span><Zap className="size-3 inline mr-0.5" />{key.requests_today} today</span>
                            <span><Timer className="size-3 inline mr-0.5" />{Math.round(key.speed_score || 0)}ms</span>
                            {isOnCooldown && (
                              <span className="text-amber-600">\u00b7 cooldown until {new Date(key.cooldown_until!).toLocaleTimeString()}</span>
                            )}
                          </div>
                        </div>
                        <div className="hidden md:block w-12">
                          <MockSparkline values={[key.speed_score || 20, key.reliability_score || 40, key.accuracy_score || 60, key.speed_score || 30, key.reliability_score || 50, key.accuracy_score || 70, key.speed_score || 25, key.reliability_score || 45]}
                            color={isHealthy ? 'hsl(160, 60%, 45%)' : 'hsl(40, 80%, 50%)'} />
                        </div>
                        {key.api_key && (
                          <button onClick={() => copyToClipboard(key.api_key!, `key-${key.id}`)}
                            className="text-muted-foreground hover:text-primary transition-colors shrink-0 opacity-0 group-hover:opacity-100" title="Copy API key">
                            {copiedKey === `key-${key.id}` ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
                          </button>
                        )}
                        <Switch checked={key.is_active === 1}
                          onCheckedChange={() => toggleActive.mutate({ id: key.id, isActive: key.is_active === 1 })}
                          disabled={toggleActive.isPending} className="shrink-0" />
{isOnCooldown && (
                           <span className="relative shrink-0">
                             <button onClick={() => clearCooldown.mutate(key.id)} disabled={clearCooldown.isPending}
                               className="text-amber-600 hover:text-amber-500 transition-colors shrink-0" title="Clear cooldown">
                               <AlertTriangle className="size-3.5" />
                             </button>
                             <HelpNode content={HELP.keyCooldown} side="top" />
                           </span>
                         )}
                        <button onClick={() => { if (confirm('Delete this key?')) deleteKey.mutate(key.id) }} disabled={deleteKey.isPending}
                          className="text-muted-foreground hover:text-destructive transition-colors shrink-0 opacity-0 group-hover:opacity-100" title="Delete key">
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    )
                  })}
                </div>
              )}
            </Card>
          )
        })}
      </div>

      {providerModal && (
        <ProviderModal
          provider={providerModal}
          keys={groupedKeys.get(providerModal) ?? []}
          models={allModels?.filter((m) => m.platform === providerModal) ?? []}
          routingOverride={routingOverride}
          onClose={() => setProviderModal(null)}
          queryClient={queryClient}
        />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════
//  ProviderModal — semi-fullscreen provider management popup
// ═══════════════════════════════════════════════════════════════════════

interface ProviderModalProps {
  provider: string
  keys: Key[]
  models: ModelRow[]
  routingOverride: { models: string[]; override_active: boolean } | undefined
  onClose: () => void
  queryClient: ReturnType<typeof useQueryClient>
}

function ProviderModal({
  provider, keys, models, routingOverride, onClose, queryClient,
}: ProviderModalProps) {
  const [tab, setTab] = useState<'keys' | 'models'>('keys')
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null)
  const [modelSearch, setModelSearch] = useState('')
  const [forcedModels, setForcedModels] = useState<string[]>(
    routingOverride?.models ?? []
  )
  const [effortTarget, setEffortTarget] = useState<{ model_id: string; platform: string } | null>(null)

  // Keep forcedModels in sync with routingOverride
  useEffect(() => {
    if (routingOverride) {
      setForcedModels(routingOverride.models)
    }
  }, [routingOverride])

  const toggleModelMutation = useMutation({
    mutationFn: (body: { model_id: string; platform: string; enabled: boolean }) =>
      apiFetch('/api/models/toggle', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-models'] })
    },
  })

  const pinModelMutation = useMutation({
    mutationFn: async (models: string[]) => {
      if (models.length === 0) {
        await apiFetch('/api/settings/routing-override', { method: 'DELETE' })
      } else {
        await apiFetch('/api/settings/routing-override', {
          method: 'POST',
          body: JSON.stringify({ models }),
        })
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['routing-override'] })
    },
  })

  const copyToClipboard = useCallback(async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopyFeedback(key)
    setTimeout(() => setCopyFeedback(null), 2000)
  }, [])

  const copyAllKeys = useCallback(async () => {
    const allKeys = keys.map((k) => k.api_key).filter(Boolean).join('\n')
    if (!allKeys) return
    try {
      await navigator.clipboard.writeText(allKeys)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = allKeys
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopyFeedback('__all__')
    setTimeout(() => setCopyFeedback(null), 2000)
  }, [keys])

  const maskKey = (k: string) => {
    if (k.length <= 8) return k
    return k.slice(0, 6) + '…' + k.slice(-4)
  }

  const filteredModels = useMemo(() => {
    if (!modelSearch) return models
    const q = modelSearch.toLowerCase()
    return models.filter((m) =>
      m.model_id.toLowerCase().includes(q) ||
      m.display_name?.toLowerCase().includes(q)
    )
  }, [models, modelSearch])

  const activeKeys = keys.filter((k) => k.is_active)

  // Effort config for a model
  const modelEffortKey = effortTarget ? `${effortTarget.platform}:${effortTarget.model_id}` : null

  const { data: currentEffort } = useQuery<{ model_key: string; params: Record<string, unknown> }>({
    queryKey: ['effort-config', modelEffortKey],
    queryFn: () => apiFetch(`/api/models/effort/${encodeURIComponent(modelEffortKey!)}`),
    enabled: !!modelEffortKey,
    staleTime: 5_000,
  })

  const { data: effortPresets } = useQuery<Record<string, Record<string, unknown>>>({
    queryKey: ['effort-presets'],
    queryFn: () => apiFetch('/api/models/effort/presets'),
    staleTime: 60_000,
  })

  const setEffortMutation = useMutation({
    mutationFn: (params: Record<string, unknown>) =>
      apiFetch('/api/models/effort', {
        method: 'PUT',
        body: JSON.stringify({ model_key: modelEffortKey, params }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['effort-config', modelEffortKey] })
      queryClient.invalidateQueries({ queryKey: ['effort-presets'] })
    },
  })

  const clearEffortMutation = useMutation({
    mutationFn: () =>
      apiFetch('/api/models/effort', {
        method: 'DELETE',
        body: JSON.stringify({ model_key: modelEffortKey }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['effort-config', modelEffortKey] })
    },
  })

  const toggleForceModel = (modelId: string) => {
    const next = forcedModels.includes(modelId)
      ? forcedModels.filter((m) => m !== modelId)
      : [...forcedModels, modelId]
    setForcedModels(next)
    pinModelMutation.mutate(next)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-6 pb-6 overflow-y-auto">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-background border border-border rounded-2xl shadow-2xl w-full max-w-5xl max-h-[92vh] flex flex-col z-10 overflow-hidden animate-scale-in">
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-bold text-foreground">{provider}</h2>
              <Badge variant="secondary" className="text-[10px]">
                {keys.length} key{keys.length !== 1 ? 's' : ''} · {activeKeys.length} active
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {models.length} synced models · Full provider management
            </p>
          </div>
          <div className="flex items-center gap-2">
            {tab === 'keys' && keys.some((k) => k.api_key) && (
              <Button
                variant="outline"
                size="sm"
                onClick={copyAllKeys}
                className="h-8 text-xs gap-1"
              >
                {copyFeedback === '__all__' ? (
                  <Check className="size-3.5 text-emerald-500" />
                ) : (
                  <Copy className="size-3.5" />
                )}
                Copy All Keys
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
              <X className="size-5" />
            </Button>
          </div>
        </div>

        {/* ── Tabs ── */}
        <div className="flex gap-0 border-b border-border px-6 shrink-0">
          <button
            onClick={() => setTab('keys')}
            className={`pb-2.5 pt-3 text-sm font-medium border-b-2 transition-colors ${
              tab === 'keys'
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            API Keys
            <span className="ml-1.5 text-xs text-muted-foreground">({keys.length})</span>
          </button>
          <button
            onClick={() => setTab('models')}
            className={`pb-2.5 pt-3 text-sm font-medium border-b-2 transition-colors ml-6 ${
              tab === 'models'
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            Models
            <span className="ml-1.5 text-xs text-muted-foreground">({models.length})</span>
          </button>
        </div>

        {/* ── Body (scrollable) ── */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'keys' && (
            <div className="space-y-3 animate-fade-in-up">
              {/* Summary bar */}
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="bg-accent/30 rounded-lg p-3">
                  <div className="text-[10px] text-muted-foreground">Total Keys</div>
                  <div className="text-lg font-bold tabular-nums">{keys.length}</div>
                </div>
                <div className="bg-accent/30 rounded-lg p-3">
                  <div className="text-[10px] text-muted-foreground">Active</div>
                  <div className="text-lg font-bold tabular-nums text-emerald-600">{activeKeys.length}</div>
                </div>
                <div className="bg-accent/30 rounded-lg p-3">
                  <div className="text-[10px] text-muted-foreground">Synced Models</div>
                  <div className="text-lg font-bold tabular-nums text-blue-600">{models.length}</div>
                </div>
              </div>

              {/* Key list */}
              <div className="space-y-2">
                {keys.length === 0 ? (
                  <div className="text-sm text-muted-foreground text-center py-8">
                    No keys for this provider.
                  </div>
                ) : (
                  keys.map((key) => (
                    <div
                      key={key.id}
                      className="flex items-center gap-3 p-3 rounded-lg border border-border bg-card hover:bg-accent/20 transition-colors"
                    >
                      {/* Status indicator */}
                      <span
                        className={`size-2.5 rounded-full shrink-0 ${
                          key.is_active
                            ? isKeyHealthySimple(key)
                              ? 'bg-emerald-500'
                              : 'bg-amber-500'
                            : 'bg-muted-foreground/30'
                        }`}
                      />

                      {/* Key info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-medium">
                            {key.api_key ? maskKey(key.api_key) : `Key #${key.id}`}
                          </span>
                          <Badge
                            variant={key.is_active ? 'default' : 'secondary'}
                            className="text-[9px] px-1.5 py-0"
                          >
                            {key.is_active ? 'active' : 'inactive'}
                          </Badge>
                          {key.cooldown_until && key.cooldown_until > new Date().toISOString() && (
                            <Badge variant="destructive" className="text-[9px] px-1.5 py-0">
                              cooldown
                            </Badge>
                          )}
                        </div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">
                          Model: {key.model || <span className="italic">default</span>}
                          {' · '}{key.requests_today} req today
                          {' · '}Group: {key.group_name}
                        </div>
                      </div>

                      {/* Copy key */}
                      <button
                        onClick={() => copyToClipboard(key.api_key ?? '', `key-${key.id}`)}
                        className="text-muted-foreground hover:text-primary transition-colors shrink-0 p-1.5 rounded hover:bg-accent"
                        title="Copy API key"
                      >
                        {copyFeedback === `key-${key.id}` ? (
                          <Check className="size-4 text-emerald-500" />
                        ) : (
                          <Copy className="size-4" />
                        )}
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {tab === 'models' && (
            <div className="space-y-4 animate-fade-in-up">
              {/* Force routing section */}
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Pin className="size-4 text-amber-600" />
                  <h3 className="text-sm font-medium">Forced Routing</h3>
                  {forcedModels.length > 0 && (
                    <Badge className="text-[10px] bg-amber-500/10 text-amber-600 border-amber-200">
                      {forcedModels.length} pinned
                    </Badge>
                  )}
                </div>
                <p className="text-[11px] text-muted-foreground mb-3">
                  Select models to force routing exclusively through these. Deselect all to allow automatic routing.
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {models.slice(0, 30).map((m) => {
                    const isForced = forcedModels.includes(m.model_id)
                    return (
                      <button
                        key={m.model_id}
                        onClick={() => toggleForceModel(m.model_id)}
                        className={`text-[10px] px-2 py-1 rounded-full border transition-all ${
                          isForced
                            ? 'bg-primary text-primary-foreground border-primary'
                            : 'bg-card text-muted-foreground border-border hover:border-primary/50'
                        }`}
                      >
                        {m.model_id}
                      </button>
                    )
                  })}
                  {models.length > 30 && (
                    <span className="text-[10px] text-muted-foreground self-center ml-1">
                      +{models.length - 30} more
                    </span>
                  )}
                </div>
              </div>

              {/* Search */}
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search models within this provider..."
                  value={modelSearch}
                  onChange={(e) => setModelSearch(e.target.value)}
                  className="pl-9 h-9 text-sm"
                />
              </div>

              {/* Model list */}
              <div className="space-y-1">
                {filteredModels.length === 0 ? (
                  <div className="text-sm text-muted-foreground text-center py-8">
                    {modelSearch
                      ? 'No models match your search.'
                      : 'No models synced for this provider. Click Sync Models.'}
                  </div>
                ) : (
                  <div className="rounded-lg border border-border overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-border bg-muted/50">
                            <th className="text-left font-medium text-muted-foreground text-[10px] px-3 py-2">Model</th>
                            <th className="text-center font-medium text-muted-foreground text-[10px] px-3 py-2 w-16">Tier</th>
                            <th className="text-center font-medium text-muted-foreground text-[10px] px-3 py-2 w-16">Context</th>
                            <th className="text-center font-medium text-muted-foreground text-[10px] px-3 py-2 w-16">Free</th>
                            <th className="text-center font-medium text-muted-foreground text-[10px] px-3 py-2 w-16">Enabled</th>
                            <th className="text-center font-medium text-muted-foreground text-[10px] px-3 py-2 w-16">Pin</th>
                            <th className="text-center font-medium text-muted-foreground text-[10px] px-3 py-2 w-16">Effort</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredModels.map((m) => {
                            const isForced = forcedModels.includes(m.model_id)
                            return (
                              <tr
                                key={m.model_id}
                                className="border-b border-border/40 last:border-0 hover:bg-muted/20 transition-colors"
                              >
                                <td className="px-3 py-2">
                                  <div className="font-mono text-[11px] font-medium truncate max-w-[320px]" title={m.model_id}>
                                    {m.model_id}
                                  </div>
                                  {m.display_name && m.display_name !== m.model_id && (
                                    <div className="text-[9px] text-muted-foreground truncate max-w-[320px]">
                                      {m.display_name}
                                    </div>
                                  )}
                                </td>
                                <td className="px-3 py-2 text-center">
                                  <span className={`text-[11px] font-medium ${
                                    m.tier === 1 ? 'text-emerald-600' :
                                    m.tier === 2 ? 'text-blue-600' :
                                    m.tier === 3 ? 'text-amber-600' :
                                    'text-orange-600'
                                  }`}>
                                    T{m.tier}
                                  </span>
                                </td>
                                <td className="px-3 py-2 text-center">
                                  <span className="text-[10px] font-mono text-muted-foreground">
                                    {m.context_window ? m.context_window.toLocaleString() : '—'}
                                  </span>
                                </td>
                                <td className="px-3 py-2 text-center">
                                  {m.is_free ? (
                                    <Globe className="size-3.5 text-emerald-500 mx-auto" />
                                  ) : (
                                    <span className="text-[10px] text-muted-foreground">—</span>
                                  )}
                                </td>
                                <td className="px-3 py-2 text-center">
                                  <Switch
                                    checked={m.enabled}
                                    onCheckedChange={() =>
                                      toggleModelMutation.mutate({
                                        model_id: m.model_id,
                                        platform: m.platform,
                                        enabled: !m.enabled,
                                      })
                                    }
                                    disabled={toggleModelMutation.isPending}
                                    className="scale-75"
                                  />
                                </td>
                                <td className="px-3 py-2 text-center">
                                  <button
                                    onClick={() => toggleForceModel(m.model_id)}
                                    className={`transition-colors ${
                                      isForced
                                        ? 'text-primary'
                                        : 'text-muted-foreground hover:text-primary'
                                    }`}
                                    title={isForced ? 'Unpin' : 'Force route'}
                                  >
                                    {isForced ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
                                  </button>
                                </td>
                                <td className="px-3 py-2 text-center">
                                  <button
                                    onClick={() => setEffortTarget({ platform: m.platform, model_id: m.model_id })}
                                    className="text-muted-foreground hover:text-primary transition-colors"
                                    title="Configure effort"
                                  >
                                    <Settings2 className="size-3.5" />
                                  </button>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Effort Config Sub-modal ── */}
      {effortTarget && effortPresets && (
        <ProviderEffortModal
          platform={provider}
          modelId={effortTarget.model_id}
          presets={effortPresets}
          currentParams={currentEffort?.params ?? null}
          isSaving={setEffortMutation.isPending || clearEffortMutation.isPending}
          onSave={(params) => setEffortMutation.mutate(params)}
          onClear={() => clearEffortMutation.mutate()}
          onClose={() => setEffortTarget(null)}
        />
      )}
    </div>
  )
}

function isKeyHealthySimple(key: Key) {
  if (!key.is_active) return false
  if (key.cooldown_until && key.cooldown_until > new Date().toISOString()) return false
  return true
}

// ═══════════════════════════════════════════════════════════════════════
//  ProviderEffortModal — inline effort config within provider modal
// ═══════════════════════════════════════════════════════════════════════

interface ProviderEffortModalProps {
  platform: string
  modelId: string
  presets: Record<string, Record<string, unknown>>
  currentParams: Record<string, unknown> | null
  isSaving: boolean
  onSave: (params: Record<string, unknown>) => void
  onClear: () => void
  onClose: () => void
}

function ProviderEffortModal({
  platform, modelId, presets, currentParams, isSaving, onSave, onClear, onClose,
}: ProviderEffortModalProps) {
  const presetNames = Object.keys(presets)
  const [selectedPreset, setSelectedPreset] = useState<string>('')

  // Detect current preset
  useEffect(() => {
    if (!currentParams || Object.keys(currentParams).length === 0) {
      setSelectedPreset('off')
      return
    }
    for (const [name, params] of Object.entries(presets)) {
      if (JSON.stringify(params) === JSON.stringify(currentParams)) {
        setSelectedPreset(name)
        return
      }
    }
    setSelectedPreset('custom')
  }, [currentParams, presets])

  const hasOverride = currentParams && Object.keys(currentParams).length > 0

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div
        className="relative bg-background border border-border rounded-xl shadow-2xl w-full max-w-sm p-5 z-10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4">
          <h3 className="text-sm font-semibold">Effort / Thinking Config</h3>
          <p className="text-xs text-muted-foreground mt-1 font-mono">{modelId}</p>
        </div>

        <div className="mb-4 p-3 rounded-lg bg-accent/30 text-xs space-y-1">
          <div className="text-muted-foreground">Status:</div>
          {hasOverride ? (
            <div className="font-mono text-[11px] text-foreground break-all">
              {JSON.stringify(currentParams)}
            </div>
          ) : (
            <div className="text-muted-foreground italic">No override — defaults apply</div>
          )}
        </div>

        <div className="space-y-2 mb-5">
          <label className="text-xs font-medium text-muted-foreground">Preset</label>
          <select
            value={selectedPreset}
            onChange={(e) => setSelectedPreset(e.target.value)}
            className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="off">Off (use defaults)</option>
            {presetNames.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
            {hasOverride && !presetNames.includes(selectedPreset) && (
              <option value="custom">Custom (current)</option>
            )}
          </select>
        </div>

        <div className="flex items-center gap-2 justify-end">
          <Button variant="outline" size="sm" onClick={onClose} className="h-8 text-xs">
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => {
              if (selectedPreset === 'off') onClear()
              else if (presets[selectedPreset]) onSave(presets[selectedPreset])
            }}
            disabled={isSaving}
            className="h-8 text-xs"
          >
            {isSaving ? <Loader2 className="size-3 animate-spin mr-1" /> : null}
            Apply
          </Button>
        </div>
      </div>
    </div>
  )
}
