interface HeaderProps {
  wsStatus: 'connecting' | 'connected' | 'disconnected'
}

const statusConfig = {
  connected: {
    dot: 'bg-green-500',
    ping: 'bg-green-400',
    text: 'text-green-400',
    label: 'System Online',
  },
  connecting: {
    dot: 'bg-yellow-500',
    ping: 'bg-yellow-400',
    text: 'text-yellow-400',
    label: 'Connecting...',
  },
  disconnected: {
    dot: 'bg-red-500',
    ping: 'bg-red-400',
    text: 'text-red-400',
    label: 'Offline — Retrying',
  },
}

export function Header({ wsStatus }: HeaderProps) {
  const cfg = statusConfig[wsStatus]

  return (
    <header className="bg-brand-800 border-b border-slate-700/60 px-4 py-3 flex justify-between items-center shrink-0 safe-top">
      <div className="flex items-center gap-3">
        <div className="bg-blue-600 p-2 rounded-xl shadow-lg shadow-blue-500/20">
          {/* CPU icon via Phosphor web font referenced in index.html */}
          <i className="ph ph-cpu text-white text-xl leading-none" />
        </div>
        <div>
          <h1 className="text-base font-bold text-white tracking-wide leading-tight">
            CoDevx
            <span className="text-blue-400 font-normal text-xs ml-1.5">Command Center</span>
          </p>
          <p className="text-[11px] text-slate-500 leading-none mt-0.5">CoDevx · Agent Mesh v2.0</p>
        </div>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="relative flex h-3 w-3">
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full ${cfg.ping} opacity-75`}
          />
          <span className={`relative inline-flex rounded-full h-3 w-3 ${cfg.dot}`} />
        </span>
        <span className={`${cfg.text} font-medium text-xs hidden sm:block`}>{cfg.label}</span>
      </div>
    </header>
  )
}
