import type { TaskHistory } from '@/types'

interface TaskHistoryListProps {
  history: TaskHistory[]
}

export function TaskHistoryList({ history }: TaskHistoryListProps) {
  if (history.length === 0) {
    return (
      <div className="text-center py-12 text-slate-600">
        <i className="ph ph-clock-counter-clockwise text-4xl block mb-3" />
        <p className="text-sm">No completed tasks yet.</p>
        <p className="text-xs mt-1">Issue your first order via Discord #orders or WhatsApp.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {[...history].reverse().map(task => (
        <div
          key={task.id}
          className="bg-brand-800 rounded-xl border border-slate-700/60 p-4"
        >
          <div className="flex items-start gap-3">
            <div className="bg-emerald-900/30 p-2 rounded-lg shrink-0 mt-0.5">
              <i className="ph ph-check-circle text-emerald-400 text-lg leading-none" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-white text-sm font-medium leading-snug break-words">{task.description}</p>
              <p className="text-slate-500 text-xs mt-1">{task.completed_at}</p>
              <div className="flex flex-wrap gap-3 mt-2">
                <span className="text-xs text-slate-400">
                  <i className="ph ph-files mr-1 text-blue-400" />
                  {task.files_modified} files
                </span>
                <span className="text-xs text-slate-400">
                  <i className="ph ph-check-square mr-1 text-emerald-400" />
                  {task.tests_passed} tests passed
                </span>
                {task.branch && (
                  <span className="text-xs text-slate-500 font-mono">
                    <i className="ph ph-git-branch mr-1 text-slate-500" />
                    {task.branch}
                  </span>
                )}
                {task.llm_used && (
                  <span className="text-xs text-purple-400">
                    <i className="ph ph-robot mr-1" />
                    LLM
                  </span>
                )}
                {task.pr_url && (
                  <a
                    href={task.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                  >
                    <i className="ph ph-git-pull-request" />
                    View PR
                  </a>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
