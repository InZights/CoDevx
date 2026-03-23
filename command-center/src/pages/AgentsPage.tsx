import { AgentGrid } from '@/components/AgentGrid'
import type { SystemState } from '@/types'
import { AGENT_CATALOG } from '@/utils/colors'

interface AgentsPageProps {
  state: SystemState
}

export function AgentsPage({ state }: AgentsPageProps) {
  const activeCount = Object.values(state.agents).filter(a => a.status !== 'IDLE').length

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="flex items-center gap-4 bg-brand-800 rounded-xl border border-slate-700/60 px-4 py-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-emerald-400 font-semibold">{activeCount}</span>
          <span className="text-slate-400">active</span>
        </div>
        <div className="h-4 w-px bg-slate-700" />
        <div className="text-sm text-slate-400">
          <span className="text-slate-300 font-semibold">{Object.keys(state.agents).length}</span> agents total
        </div>
        <div className="h-4 w-px bg-slate-700 hidden md:block" />
        <div className="text-xs text-slate-500 font-mono hidden md:block">
          PM → Architect → (FE+BE) → DB → QA → SecOps → DevOps
        </div>
      </div>

      {/* Full grid — 1 col mobile, 2 cols sm, 4 cols xl */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {Object.entries(state.agents).map(([name, info]) => {
          const catalog = AGENT_CATALOG[name] ?? { role: name, icon: 'ph-robot', description: '', tools: [] }
          return (
            <div
              key={name}
              className="bg-brand-800 rounded-xl border border-slate-700/60 p-4 space-y-3"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 bg-slate-900 rounded-lg">
                  <i className={`ph ${catalog.icon} text-2xl leading-none`} />
                </div>
                <div className="min-w-0">
                  <p className="font-bold text-white text-sm truncate">{name}</p>
                  <p className="text-[11px] text-slate-500 truncate">{catalog.role}</p>
                </div>
              </div>
              <p className="text-xs text-slate-500 leading-relaxed">{catalog.description}</p>
              <div className="flex flex-wrap gap-1">
                {catalog.tools.map((t) => (
                  <span key={t} className="text-[10px] bg-slate-900/60 border border-slate-700/50 text-slate-500 px-1.5 py-0.5 rounded font-mono">
                    {t}
                  </span>
                ))}
              </div>
              <div className="pt-2 border-t border-slate-700/40">
                <span className={`text-[10px] font-mono font-bold uppercase tracking-wider ${
                  info.status !== 'IDLE' ? 'text-blue-400 animate-pulse' : 'text-slate-600'
                }`}>
                  {info.status}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Compact list on screens where grid is hidden */}
      <div className="sm:hidden">
        <AgentGrid agents={state.agents} />
      </div>
    </div>
  )
}
