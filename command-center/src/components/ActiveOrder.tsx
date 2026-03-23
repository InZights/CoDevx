interface ActiveOrderProps {
  task: string
}

export function ActiveOrder({ task }: ActiveOrderProps) {
  const hasTask = task !== 'None' && task.trim() !== ''

  return (
    <div className="bg-brand-800 rounded-xl border border-slate-700/60 p-4 shadow-lg">
      <h2 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-3 flex items-center gap-2">
        <i className="ph ph-target-duotone" />
        Active Order
      </h2>

      <div
        className={`rounded-lg p-3.5 border transition-all duration-500 ${
          hasTask
            ? 'bg-blue-950/40 border-blue-500/30 shadow-[0_0_20px_rgba(59,130,246,0.08)]'
            : 'bg-slate-900/50 border-slate-700/40'
        }`}
      >
        {hasTask ? (
          <p className="text-white font-medium break-words text-sm leading-relaxed">
            <span className="text-blue-400 font-mono text-xs mr-1.5">&gt;</span>
            {task}
          </p>
        ) : (
          <p className="text-slate-600 italic text-sm">
            No active orders. Awaiting Architect command.
          </p>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2 text-xs text-slate-600">
        <i className="ph ph-discord-logo text-lg text-[#5865F2]" />
        <span>
          Issue orders in&nbsp;
          <span className="text-slate-400 font-mono bg-slate-800 px-1.5 py-0.5 rounded">
            #orders
          </span>
          &nbsp;using&nbsp;
          <span className="text-slate-400 font-mono bg-slate-800 px-1.5 py-0.5 rounded">
            !order &lt;task&gt;
          </span>
        </span>
      </div>
    </div>
  )
}
