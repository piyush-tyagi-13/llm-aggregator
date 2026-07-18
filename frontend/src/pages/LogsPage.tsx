import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Download, FileText, HardDrive, Calendar, Loader2, Terminal, Database, Archive } from 'lucide-react'
import { HelpNode } from '@/components/ui/help-node'
import { HELP } from '@/lib/help-text'

type LogType = 'audit' | 'access' | 'proxy'
type LogFormat = 'csv' | 'json' | 'jsonl'

interface LogInfo {
  type: LogType
  file_count: number
  total_size_mb: number
  days_available: number
  oldest: string
  newest: string
}

const LOG_TYPE_CONFIG: Record<LogType, { icon: typeof Terminal; label: string; desc: string }> = {
  audit: { icon: Database, label: 'Audit Log', desc: 'API call audit trail — who called what, when, and which key was used' },
  access: { icon: Terminal, label: 'Access Log', desc: 'HTTP access log — requests, status codes, latency' },
  proxy: { icon: Archive, label: 'Proxy Log', desc: 'Full proxy request/response log including model output' },
}

export function LogsPage() {
  const [logType, setLogType] = useState<LogType>('audit')
  const [logFormat, setLogFormat] = useState<LogFormat>('csv')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  const { data: logInfo, isLoading } = useQuery<LogInfo>({
    queryKey: ['log-info', logType],
    queryFn: () => apiFetch(`/api/logs/info?type=${logType}`),
    staleTime: 30_000,
  })

  const logConfig = LOG_TYPE_CONFIG[logType]
  const LogIcon = logConfig.icon

  function handleDownload() {
    const params = new URLSearchParams({ type: logType, format: logFormat })
    if (startDate) params.set('from', startDate)
    if (endDate) params.set('to', endDate)
    window.open(`/api/logs/download?${params.toString()}`, '_blank')
  }

  return (
    <div>
      <PageHeader
        title="Logs"
        description="Download audit, access, and proxy logs for offline analysis"
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Configuration */}
        <div className="lg:col-span-2 space-y-6">
          {/* Log Type Selector */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Log Type <HelpNode content={HELP.logTypeSelector} side="top" />
              </CardTitle>
              <CardDescription>Select the log category to download</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {(Object.entries(LOG_TYPE_CONFIG) as [LogType, typeof LOG_TYPE_CONFIG[LogType]][]).map(([type, cfg]) => {
                  const Icon = cfg.icon
                  const isActive = logType === type
                  return (
                    <button
                      key={type}
                      onClick={() => setLogType(type)}
                      className={`relative flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-all duration-200 ${
                        isActive
                          ? 'border-primary bg-primary/5 shadow-elevated'
                          : 'border-border hover:border-border/60 hover:bg-muted/30'
                      }`}
                    >
                      <Icon className={`size-6 ${isActive ? 'text-primary' : 'text-muted-foreground'}`} />
                      <span className={`text-sm font-semibold ${isActive ? 'text-foreground' : 'text-muted-foreground'}`}>
                        {cfg.label}
                      </span>
                      <span className="text-[10px] text-muted-foreground text-center leading-tight">
                        {cfg.desc}
                      </span>
                    </button>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* Date Range + Format */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Export Settings <HelpNode content={HELP.logDateRange} side="top" />
              </CardTitle>
              <CardDescription>Configure date range and output format</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <Calendar className="size-3" /> Start Date
                  </Label>
                  <Input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="h-9 text-sm"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <Calendar className="size-3" /> End Date
                  </Label>
                  <Input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="h-9 text-sm"
                  />
                </div>
              </div>

              <Separator className="my-4" />

              <div className="space-y-1.5">
<Label className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <FileText className="size-3" /> Format <HelpNode content={HELP.logFormat} side="top" />
                  </Label>
                <div className="flex gap-2">
                  {(['csv', 'json', 'jsonl'] as LogFormat[]).map((fmt) => (
                    <button
                      key={fmt}
                      onClick={() => setLogFormat(fmt)}
                      className={`px-4 py-2 rounded-lg text-sm font-medium border transition-all duration-200 ${
                        logFormat === fmt
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border text-muted-foreground hover:border-muted-foreground/30'
                      }`}
                    >
                      {fmt.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              <Separator className="my-4" />

              <Button
                size="lg"
                onClick={handleDownload}
                className="w-full sm:w-auto"
              >
                <Download className="size-4 mr-2" />
                Download {logConfig.label}
              </Button>
            </CardContent>
          </Card>

          {/* Real-time tail section */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">Live Tail <HelpNode content={HELP.logLiveTail} side="top" /></CardTitle>
              <CardDescription>Stream real-time log entries via SSE</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground mb-4">
                Connect to the SSE endpoint for real-time log streaming. Use the terminal command below.
              </p>
              <div className="bg-muted rounded-lg p-4 font-mono text-xs">
                <div className="text-muted-foreground mb-1"># Stream {logConfig.label.toLowerCase()} in real-time:</div>
                <div className="text-foreground">curl -N http://localhost:8000/api/logs/stream?type={logType}</div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right: Storage Info */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <HardDrive className="size-4 text-primary" />
                Storage Info <HelpNode content={HELP.logStorage} side="top" />
              </CardTitle>
              <CardDescription>Log file details for {logConfig.label}</CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="size-5 animate-spin text-muted-foreground" />
                </div>
              ) : logInfo ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg bg-muted/50 p-3">
                      <div className="text-[10px] text-muted-foreground">Files</div>
                      <div className="text-lg font-bold tabular-nums text-foreground">{logInfo.file_count}</div>
                    </div>
                    <div className="rounded-lg bg-muted/50 p-3">
                      <div className="text-[10px] text-muted-foreground">Total Size</div>
                      <div className="text-lg font-bold tabular-nums text-foreground">{logInfo.total_size_mb.toFixed(1)} MB</div>
                    </div>
                    <div className="rounded-lg bg-muted/50 p-3">
                      <div className="text-[10px] text-muted-foreground">Days Available</div>
                      <div className="text-lg font-bold tabular-nums text-foreground">{logInfo.days_available}</div>
                    </div>
                    <div className="rounded-lg bg-muted/50 p-3">
                      <div className="text-[10px] text-muted-foreground">Newest</div>
                      <div className="text-xs font-medium tabular-nums text-foreground truncate">{logInfo.newest}</div>
                    </div>
                  </div>
                  <div className="rounded-lg bg-muted/50 p-3">
                    <div className="text-[10px] text-muted-foreground">Oldest Entry</div>
                    <div className="text-xs font-medium tabular-nums text-foreground">{logInfo.oldest}</div>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground text-center py-8">
                  No log data available
                </div>
              )}
            </CardContent>
          </Card>

          {/* Quick Stats Card */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Database className="size-4 text-primary" />
                Data Management <HelpNode content={HELP.dataManagement} side="top" />
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Logs are stored in the SQLite database. Use the settings page to configure log retention.
              </p>
              <Button variant="outline" size="sm" className="w-full text-xs" onClick={() => window.location.href = '/settings'}>
                Configure Log Retention
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
