import { useEffect, useRef, useState, useCallback } from 'react'
import ReconnectingWebSocket from 'reconnecting-websocket'
import type { SystemState } from '@/types'

const DEFAULT_STATE: SystemState = {
  agents: {},
  current_task: 'None',
  logs: ['Connecting to Agent Mesh...'],
  history: [],
  connected: false,
}

function buildWsUrl(): string {
  const base = import.meta.env.VITE_BACKEND_URL as string | undefined
  if (base) {
    return base.replace(/^http/, 'ws') + '/ws/state'
  }
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/state`
}

export function useAgentState() {
  const [state, setState] = useState<SystemState>(DEFAULT_STATE)
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const wsRef = useRef<ReconnectingWebSocket | null>(null)

  const connect = useCallback(() => {
    const ws = new ReconnectingWebSocket(buildWsUrl(), [], {
      maxRetries: Infinity,
      minReconnectionDelay: 1000,
      maxReconnectionDelay: 10000,
      reconnectionDelayGrowFactor: 1.5,
    })

    ws.addEventListener('open', () => {
      setWsStatus('connected')
      setState(prev => ({ ...prev, connected: true }))
    })

    ws.addEventListener('close', () => {
      setWsStatus('disconnected')
      setState(prev => ({ ...prev, connected: false }))
    })

    ws.addEventListener('error', () => {
      setWsStatus('disconnected')
    })

    ws.addEventListener('message', (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string)
        if (msg.type === 'state_update' && msg.payload) {
          setState(prev => ({ ...prev, ...msg.payload, connected: true }))
        }
      } catch {
        // malformed message — ignore
      }
    })

    wsRef.current = ws
  }, [])

  // REST fallback — polls /api/state every 2s if WS is disconnected
  useEffect(() => {
    if (wsStatus !== 'disconnected') return
    const id = setInterval(async () => {
      try {
        const res = await fetch('/api/state')
        if (res.ok) {
          const data = await res.json() as SystemState
          setState({ ...data, connected: false })
        }
      } catch {
        // server unreachable
      }
    }, 2000)
    return () => clearInterval(id)
  }, [wsStatus])

  useEffect(() => {
    connect()
    return () => wsRef.current?.close()
  }, [connect])

  return { state, wsStatus }
}
