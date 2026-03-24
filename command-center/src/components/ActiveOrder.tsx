import { useState, type FormEvent } from 'react'

interface ActiveOrderProps {
  task: string
}

export function ActiveOrder({ task }: ActiveOrderProps) {
  const hasTask = task !== 'None' && task.trim() !== ''
  const [input, setInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed) return
    setSubmitting(true)
    setError('')
    try {
      const backendUrl =
        localStorage.getItem('codevx_backend_url') ?? 'http://localhost:8000'
      const resp = await fetch(`${backendUrl}/api/order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: trimmed }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        setError((data as { detail?: string }).detail ?? `Error ${resp.status}`)
      } else {
        setInput('')
      }
    } catch {
      setError('Could not reach the backend. Is it running?')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="bg-brand-800 rounded-xl border border-slate-700/60 p-4 shadow-lg">
      <h2 className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-3 flex items-center gap-2">
        <i className="ph ph-target-duotone" />
        Active Order
      </h2>

      {/* Current task display */}
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
            No active orders. Submit one below or use Discord.
          </p>
        )}
      </div>

      {/* Order submission form */}
      {!hasTask && (
        <form onSubmit={handleSubmit} className="mt-3 flex flex-col gap-2">
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Describe a task to build…"
              disabled={submitting}
              className="flex-1 min-w-0 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/30 disabled:opacity-50 transition-colors"
              aria-label="Task description"
            />
            <button
              type="submit"
              disabled={submitting || !input.trim()}
              className="shrink-0 px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-semibold transition-colors disabled:cursor-not-allowed"
              aria-label="Submit order"
            >
              {submitting ? (
                <i className="ph ph-circle-notch animate-spin text-base leading-none" />
              ) : (
                <i className="ph ph-paper-plane-tilt text-base leading-none" />
              )}
            </button>
          </div>
          {error && (
            <p className="text-xs text-red-400 flex items-center gap-1">
              <i className="ph ph-warning-circle" /> {error}
            </p>
          )}
        </form>
      )}

      {/* Discord hint */}
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-600">
        <i className="ph ph-discord-logo text-lg text-[#5865F2]" />
        <span>
          Or issue in&nbsp;
          <span className="text-slate-400 font-mono bg-slate-800 px-1.5 py-0.5 rounded">
            #orders
          </span>
          &nbsp;via&nbsp;
          <span className="text-slate-400 font-mono bg-slate-800 px-1.5 py-0.5 rounded">
            !order &lt;task&gt;
          </span>
        </span>
      </div>
    </div>
  )
}

