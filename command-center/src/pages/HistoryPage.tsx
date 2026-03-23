import { TaskHistoryList } from '@/components/TaskHistoryList'
import type { SystemState } from '@/types'

interface HistoryPageProps {
  state: SystemState
}

export function HistoryPage({ state }: HistoryPageProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-2">
          <i className="ph ph-clock-counter-clockwise" />
          Completed Tasks
        </h2>
        <span className="text-[10px] text-slate-600 font-mono">
          {state.history?.length ?? 0} records
        </span>
      </div>
      <TaskHistoryList history={state.history ?? []} />
    </div>
  )
}
