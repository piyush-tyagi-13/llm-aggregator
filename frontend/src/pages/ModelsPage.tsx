import { useState } from 'react'
import { AvailableModelsPanel } from './models/AvailableModelsPanel'
import { UnlockableModelsPanel } from './models/UnlockableModelsPanel'
import { ModelHealthPanel } from './models/ModelHealthPanel'

const TABS = [
  { id: 'available', label: 'Available', description: 'Free models you can use now' },
  { id: 'unlockable', label: 'Unlockable', description: 'Free models you could unlock' },
  { id: 'health', label: 'Health', description: 'Cooldowns & rate-limit status' },
] as const

type TabId = (typeof TABS)[number]['id']

export function ModelsPage() {
  const [activeTab, setActiveTab] = useState<TabId>('available')

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 border-b border-border px-6 bg-background">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              relative px-4 py-3 text-sm font-medium transition-colors
              ${activeTab === tab.id
                ? 'text-foreground'
                : 'text-muted-foreground hover:text-foreground/80'
              }
            `}
          >
            {tab.label}
            {activeTab === tab.id && (
              <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-foreground rounded-full" />
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto">
        {activeTab === 'available' && <AvailableModelsPanel />}
        {activeTab === 'unlockable' && <UnlockableModelsPanel />}
        {activeTab === 'health' && <ModelHealthPanel />}
      </div>
    </div>
  )
}
