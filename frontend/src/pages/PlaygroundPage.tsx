import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { apiFetch } from '@/lib/api'
import { PageHeader } from '@/components/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Send, Loader2, Clock, Copy, Check } from 'lucide-react'

interface ChatResponse {
  choices: { message: { content: string } }[]
}

interface Model {
  id: string
  owned_by: string
}

export function PlaygroundPage() {
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [response, setResponse] = useState('')
  const [latency, setLatency] = useState<number | null>(null)
  const [copied, setCopied] = useState(false)

  const { data: modelsData } = useQuery<{ data: Model[] }>({
    queryKey: ['models'],
    queryFn: () => apiFetch('/v1/models'),
  })

  const testPrompt = useMutation({
    mutationFn: async () => {
      const start = Date.now()
      const data = await apiFetch<ChatResponse>('/v1/chat/completions', {
        method: 'POST',
        body: JSON.stringify({
          model,
          messages: [{ role: 'user', content: prompt }],
        }),
      })
      setLatency(Date.now() - start)
      return data.choices[0].message.content
    },
    onSuccess: (content) => setResponse(content),
    onError: (err: Error) => setResponse(`Error: ${err.message}`),
  })

  const models = modelsData?.data ?? []

  function copyResponse() {
    navigator.clipboard.writeText(response)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div>
      <PageHeader
        title="Playground"
        description="Test prompts through the LLM pool proxy"
      />

      <div className="space-y-4">
        <Card>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-xs">Model</Label>
              <Select value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="">Select Model</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.id} ({m.owned_by})</option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Prompt</Label>
              <Textarea
                placeholder="Enter your prompt..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                className="min-h-[120px] font-mono text-sm"
              />
            </div>

            <div className="flex items-center gap-3">
              <Button
                onClick={() => testPrompt.mutate()}
                disabled={testPrompt.isPending || !model || !prompt}
              >
                {testPrompt.isPending ? (
                  <Loader2 className="size-4 animate-spin mr-2" />
                ) : (
                  <Send className="size-4 mr-2" />
                )}
                Send
              </Button>
              {latency !== null && (
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="size-3" /> {latency}ms
                </span>
              )}
            </div>
          </CardContent>
        </Card>

        {(response || testPrompt.isError) && (
          <Card>
            <CardContent>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-xs">Response</Label>
                <Button variant="ghost" size="xs" onClick={copyResponse}>
                  {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
                </Button>
              </div>
              <div className="bg-muted rounded-lg p-4">
                <pre className="whitespace-pre-wrap text-sm font-mono">{response}</pre>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
