import { useRef, useEffect, useState, useMemo } from 'react'

interface TerminalLogsProps {
  logs: string[]
  maxHeight?: string
  searchable?: boolean
}

function classifyLog(log: string): string {
  if (/passed|✅|success|complete|done/i.test(log)) return 'text-emerald-400'
  if (/❌|error|failed|rejected|critical/i.test(log)) return 'text-red-400'
  if (/warn|caution|⚠/i.test(log)) return 'text-yellow-400'
  if (/manager:|coder:|auditor:|architect:|frontend|backend|qa|devops|security|database/i.test(log)) return 'text-blue-300'
  if (/system|initialized|booting|connecting/i.test(log)) return 'text-purple-400'
  return 'text-slate-300'
}

export function TerminalLogs({ logs, maxHeight = 'flex-1', searchable = false }: TerminalLogsProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState('')
  const prevLogsLen = useRef(logs.length)

  const filtered = useMemo(() => {
    if (!filter) return logs
    const q = filter.toLowerCase()
    return logs.filter(l => l.toLowerCase().includes(q))
  }, [logs, filter])

  // Auto-scroll when new logs arrive
  useEffect(() => {
    if (autoScroll && containerRef.current && logs.length !== prevLogsLen.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
    prevLogsLen.current = logs.length
  }, [logs, autoScroll])

  function handleScroll() {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.clientHeight - el.scrollTop < 40
    setAutoScroll(atBottom)
  }

  return (
    <div className="flex flex-col bg-brand-800 rounded-xl border border-slate-700/60 shadow-lg overflow-hidden h-full">
      {/* Title bar */}
      <div className="bg-slate-900/80 border-b border-slate-700/60 px-3 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-500/80" />
            <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
            <div className="w-3 h-3 rounded-full bg-emerald-500/80" />
          </div>
          <span className="text-xs font-mono text-slate-400 ml-2">mesh_gateway.log</span>
        </div>
        <div className="flex items-center gap-2">
          {!autoScroll && (
            <button
              onClick={() => {
                setAutoScroll(true)
                containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' })
              }}
              className="text-[10px] text-blue-400 hover:text-blue-300 px-2 py-0.5 rounded bg-blue-900/30 border border-blue-500/30"
            >
              ↓ Jump to latest
            </button>
          )}
          <span className="text-[10px] text-slate-600 font-mono">{logs.length} lines</span>
        </div>
      </div>

      {/* Optional search */}
      {searchable && (
        <div className="border-b border-slate-700/40 px-3 py-2 shrink-0">
          <input
            type="search"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Filter logs..."
            className="w-full bg-slate-900/60 border border-slate-700/50 rounded-md px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-blue-500/50"
          />
        </div>
      )}

      {/* Log output */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className={`${maxHeight} overflow-y-auto font-mono text-xs leading-relaxed p-3 space-y-0.5 scrollbar-thin scrollbar-track-slate-900 scrollbar-thumb-slate-700`}
      >
        {filtered.length === 0 && (
          <p className="text-slate-700 italic">No logs match the filter.</p>
        )}
        {filtered.map((log, i) => (
          <div key={i} className={`${classifyLog(log)} whitespace-pre-wrap break-all`}>
            {log}
          </div>
        ))}
      </div>
    </div>
  )
}
