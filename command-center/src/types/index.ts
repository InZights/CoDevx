// ============================================================
// Shared TypeScript types for the Command Center UI
// ============================================================

export type AgentColor = 'gray' | 'blue' | 'yellow' | 'green' | 'red' | 'purple' | 'orange' | 'cyan'

export type AgentStatus =
  | 'IDLE'
  | 'THINKING...'
  | 'DESIGNING...'
  | 'CODING...'
  | 'TESTING...'
  | 'SCANNING...'
  | 'DEPLOYING...'
  | 'MIGRATING...'
  | 'WAITING APPROVAL'
  | 'OBSERVING'
  | 'REPORTING...'
  | 'ERROR'

export interface AgentInfo {
  status: AgentStatus | string
  color: AgentColor
}

export interface LogEntry {
  raw: string
  type: 'success' | 'error' | 'agent' | 'system' | 'info'
}

export interface TaskHistory {
  id: string
  description: string
  completed_at: string
  files_modified: number
  tests_passed: number
  pr_url?: string | null
  branch?: string
  llm_used?: boolean | number
}

export interface AgentDetail {
  name: string
  role: string
  icon: string
  description: string
  tools: string[]
  status: AgentInfo
  log?: string[]
}

export interface SystemState {
  agents: Record<string, AgentInfo>
  current_task: string
  logs: string[]
  history?: TaskHistory[]
  connected?: boolean
  messaging?: 'discord' | 'whatsapp' | 'both' | 'zeroclaw'
  llm_enabled?: boolean
  git_enabled?: boolean
  zeroclaw_enabled?: boolean
  // v4.0 pipeline settings
  real_tools_enabled?: boolean
  docker_build_enabled?: boolean
  max_retries?: number
  max_subtasks?: number
  openai_max_tokens?: number
}

export interface WSMessage {
  type: 'state_update' | 'log' | 'ping'
  payload: Partial<SystemState>
}
