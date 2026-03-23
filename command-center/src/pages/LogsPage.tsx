import { TerminalLogs } from '@/components/TerminalLogs'
import type { SystemState } from '@/types'

interface LogsPageProps {
  state: SystemState
}

export function LogsPage({ state }: LogsPageProps) {
  return (
    <div className="h-full flex flex-col gap-3">
      <div className="flex items-center justify-between shrink-0">
        <h2 className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-2">
          <i className="ph ph-terminal" />
          Activity Stream
        </h2>
        <span className="text-[10px] text-slate-600 font-mono">{state.logs.length} entries</span>
      </div>
      <div className="flex-1 min-h-0">
        <TerminalLogs logs={state.logs} maxHeight="h-full" searchable />
      </div>
    </div>
  )
}
