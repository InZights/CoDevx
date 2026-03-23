import { AgentCard } from './AgentCard'
import type { AgentInfo } from '@/types'

interface AgentGridProps {
  agents: Record<string, AgentInfo>
  compact?: boolean
}

// Keep consistent order matching the pipeline
const AGENT_ORDER = [
  'Project Manager',
  'Architect',
  'Frontend Dev',
  'Backend Dev',
  'QA Engineer',
  'DevOps Engineer',
  'Security Analyst',
  'Database Engineer',
]

export function AgentGrid({ agents, compact = false }: AgentGridProps) {
  const ordered = Object.entries(agents).sort(([a], [b]) => {
    const ai = AGENT_ORDER.indexOf(a)
    const bi = AGENT_ORDER.indexOf(b)
    if (ai === -1 && bi === -1) return a.localeCompare(b)
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })

  const activeCount = ordered.filter(([, info]) => info.status !== 'IDLE').length

  return (
    <div>
      {!compact && (
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-2">
            <i className="ph ph-users-three" />
            AI Squad
          </h2>
          <span className="text-xs text-slate-500">
            {activeCount > 0 ? (
              <span className="text-emerald-400 font-semibold">{activeCount} active</span>
            ) : (
              'All idle'
            )}
            &nbsp;/ {ordered.length} agents
          </span>
        </div>
      )}

      <div className={`grid gap-2.5 ${compact ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-1'}`}>
        {ordered.map(([name, info]) => (
          <AgentCard key={name} name={name} info={info} compact={compact} />
        ))}
      </div>
    </div>
  )
}
