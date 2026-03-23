import { ActiveOrder } from '@/components/ActiveOrder'
import { AgentGrid } from '@/components/AgentGrid'
import { TerminalLogs } from '@/components/TerminalLogs'
import type { SystemState } from '@/types'

interface DashboardProps {
  state: SystemState
}

export function Dashboard({ state }: DashboardProps) {
  return (
    <div className="flex flex-col lg:flex-row gap-4 h-full overflow-hidden">
      {/* Left column */}
      <div className="flex flex-col gap-4 lg:w-80 xl:w-96 shrink-0 lg:overflow-y-auto lg:pr-1">
        <ActiveOrder task={state.current_task} />
        <div className="bg-brand-800 rounded-xl border border-slate-700/60 p-4 shadow-lg">
          <AgentGrid agents={state.agents} />
        </div>
      </div>

      {/* Right column — terminal logs, flex-1 on desktop */}
      <div className="flex-1 min-h-0 min-h-[320px] lg:min-h-0">
        <TerminalLogs logs={state.logs} maxHeight="h-full" />
      </div>
    </div>
  )
}
