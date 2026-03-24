import { useParams, useNavigate } from 'react-router-dom'
import type { SystemState } from '@/types'
import { colorMap, AGENT_CATALOG } from '@/utils/colors'

interface AgentDetailPageProps {
  state: SystemState
}

export function AgentDetailPage({ state }: AgentDetailPageProps) {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()

  const agentName = decodeURIComponent(name ?? '')
  const info = state.agents[agentName]
  const catalog = AGENT_CATALOG[agentName]

  if (!info || !catalog) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-slate-500">
        <i className="ph ph-robot text-4xl" />
        <p className="text-sm">Agent &ldquo;{agentName}&rdquo; not found.</p>
        <button
          onClick={() => navigate('/agents')}
          className="text-xs text-blue-400 hover:underline"
        >
          ← Back to team
        </button>
      </div>
    )
  }

  const colors = colorMap[info.color] ?? colorMap.gray
  const isActive = info.status !== 'IDLE'

  // Pull last 30 logs mentioning this agent
  const agentLogs = state.logs
    .filter((line) => line.includes(`[${agentName}]`) || line.includes(agentName))
    .slice(-30)
    .reverse()

  return (
    <div className="max-w-2xl mx-auto py-4 flex flex-col gap-6">
      {/* Back button */}
      <button
        onClick={() => navigate('/agents')}
        className="self-start flex items-center gap-1 text-slate-500 hover:text-slate-300 text-xs transition-colors"
      >
        <i className="ph ph-arrow-left" />
        Back to team
      </button>

      {/* Agent header card */}
      <div className={`rounded-xl border p-5 flex items-start gap-4 ${colors}`}>
        <div className="p-3 bg-slate-900/60 rounded-xl shrink-0">
          <i className={`ph ${catalog.icon} text-3xl leading-none`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="font-bold text-white text-lg leading-tight">{agentName}</h1>
            {isActive && (
              <span className="text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full bg-white/10 border border-white/20">
                {info.status}
              </span>
            )}
          </div>
          <p className="text-xs opacity-60 mt-0.5 mb-2">{catalog.role}</p>
          <p className="text-sm opacity-80 leading-relaxed">{catalog.description}</p>
        </div>
      </div>

      {/* Tools */}
      <section className="bg-brand-800 rounded-xl border border-slate-700/60 p-4">
        <h2 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-3">
          Tools
        </h2>
        <div className="flex flex-wrap gap-2">
          {catalog.tools.map((tool) => (
            <span
              key={tool}
              className="text-xs font-mono px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-300"
            >
              {tool}
            </span>
          ))}
        </div>
      </section>

      {/* Recent activity */}
      <section className="bg-brand-800 rounded-xl border border-slate-700/60 p-4">
        <h2 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-3 flex items-center gap-2">
          <i className="ph ph-terminal-window" />
          Recent Activity
        </h2>
        {agentLogs.length === 0 ? (
          <p className="text-slate-600 italic text-sm">No recent activity.</p>
        ) : (
          <ul className="space-y-1 font-mono text-xs text-slate-300 max-h-64 overflow-y-auto">
            {agentLogs.map((line, i) => (
              <li key={i} className="leading-relaxed">
                {line}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
