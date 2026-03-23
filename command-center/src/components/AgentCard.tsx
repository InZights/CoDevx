import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import type { AgentInfo } from '@/types'
import { colorMap, pingColorMap, AGENT_CATALOG } from '@/utils/colors'

interface AgentCardProps {
  name: string
  info: AgentInfo
  compact?: boolean
}

export function AgentCard({ name, info, compact = false }: AgentCardProps) {
  const navigate = useNavigate()
  const catalog = AGENT_CATALOG[name]
  const colors = colorMap[info.color] ?? colorMap.gray
  const pingColor = pingColorMap[info.color] ?? 'hidden'
  const isActive = info.status !== 'IDLE'
  const icon = catalog?.icon ?? 'ph-robot'
  const role = catalog?.role ?? name

  return (
    <motion.button
      layout
      onClick={() => navigate(`/agents/${encodeURIComponent(name)}`)}
      whileTap={{ scale: 0.97 }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`w-full text-left flex items-center gap-3 p-3 rounded-xl border transition-all duration-300 cursor-pointer min-h-[64px] ${colors} ${
        compact ? 'py-2.5' : 'py-3'
      }`}
      aria-label={`${name} — ${info.status}`}
    >
      {/* Icon with active pulse */}
      <div className="relative shrink-0 p-2 bg-slate-900/60 rounded-lg">
        <i className={`ph ${icon} text-2xl leading-none`} />
        <AnimatePresence>
          {isActive && (
            <motion.span
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0 }}
              className="absolute -top-1 -right-1 flex h-3 w-3"
            >
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full ${pingColor} opacity-75`}
              />
              <span className={`relative inline-flex rounded-full h-3 w-3 ${pingColor}`} />
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="font-bold text-white text-sm leading-tight truncate">{name}</p>
        <p className="text-[11px] opacity-60 truncate leading-tight mt-0.5">{role}</p>
      </div>

      {/* Status badge */}
      <div className="shrink-0 text-right">
        <span
          className={`text-[10px] font-mono font-bold tracking-wider uppercase ${
            isActive ? 'animate-pulse' : 'opacity-50'
          }`}
        >
          {info.status}
        </span>
      </div>
    </motion.button>
  )
}
