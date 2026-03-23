import type { AgentColor, AgentDetail } from '@/types'

// ============================================================
// Color utilities for agent status
// ============================================================

export const colorMap: Record<AgentColor, string> = {
  gray:   'bg-slate-800/60 border-slate-600/50 text-slate-400',
  blue:   'bg-blue-900/30 border-blue-500/50 text-blue-400 shadow-[0_0_18px_rgba(59,130,246,0.2)]',
  yellow: 'bg-yellow-900/30 border-yellow-500/50 text-yellow-400 shadow-[0_0_18px_rgba(234,179,8,0.2)]',
  green:  'bg-emerald-900/30 border-emerald-500/50 text-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.2)]',
  red:    'bg-red-900/30 border-red-500/50 text-red-400 shadow-[0_0_18px_rgba(248,113,113,0.2)]',
  purple: 'bg-purple-900/30 border-purple-500/50 text-purple-400 shadow-[0_0_18px_rgba(167,139,250,0.2)]',
  orange: 'bg-orange-900/30 border-orange-500/50 text-orange-400 shadow-[0_0_18px_rgba(251,146,60,0.2)]',
  cyan:   'bg-cyan-900/30 border-cyan-500/50 text-cyan-400 shadow-[0_0_18px_rgba(34,211,238,0.2)]',
}

export const pingColorMap: Record<AgentColor, string> = {
  gray:   'hidden',
  blue:   'bg-blue-400',
  yellow: 'bg-yellow-400',
  green:  'bg-emerald-400',
  red:    'bg-red-400',
  purple: 'bg-purple-400',
  orange: 'bg-orange-400',
  cyan:   'bg-cyan-400',
}

export const dotColorMap: Record<AgentColor, string> = {
  gray:   'bg-slate-500',
  blue:   'bg-blue-400',
  yellow: 'bg-yellow-400',
  green:  'bg-emerald-400',
  red:    'bg-red-400',
  purple: 'bg-purple-400',
  orange: 'bg-orange-400',
  cyan:   'bg-cyan-400',
}

// ============================================================
// Agent catalog — full 8-agent SDLC team
// ============================================================

export const AGENT_CATALOG: Record<string, Omit<AgentDetail, 'status'>> = {
  'Project Manager': {
    name: 'Project Manager',
    role: 'Lead Orchestrator',
    icon: 'ph-strategy',
    description: 'Decomposes orders into tasks, coordinates the team, and tracks overall delivery.',
    tools: ['discord', 'planner', 'git'],
  },
  'Architect': {
    name: 'Architect',
    role: 'System Designer',
    icon: 'ph-blueprint',
    description: 'Reviews codebase structure, designs APIs, defines interfaces, and validates tech decisions.',
    tools: ['codebase-search', 'read-file', 'filesystem'],
  },
  'Frontend Dev': {
    name: 'Frontend Dev',
    role: 'UI Engineer',
    icon: 'ph-browser',
    description: 'Builds React + TypeScript components. Mobile-first, Tailwind CSS, WCAG 2.1 accessible.',
    tools: ['filesystem', 'shell', 'npm'],
  },
  'Backend Dev': {
    name: 'Backend Dev',
    role: 'API Engineer',
    icon: 'ph-code',
    description: 'Writes FastAPI endpoints with Python 3.12 type hints, Pydantic models, async/await.',
    tools: ['filesystem', 'shell', 'python'],
  },
  'QA Engineer': {
    name: 'QA Engineer',
    role: 'Test Lead',
    icon: 'ph-shield-check',
    description: 'Writes and runs Pytest + Vitest test suites. Enforces 80% coverage gate.',
    tools: ['pytest', 'vitest', 'coverage', 'shell'],
  },
  'DevOps Engineer': {
    name: 'DevOps Engineer',
    role: 'Infrastructure & CI',
    icon: 'ph-git-branch',
    description: 'Builds Docker images, GitHub Actions CI/CD pipelines, and manages deployments.',
    tools: ['docker', 'github-actions', 'shell', 'filesystem'],
  },
  'Security Analyst': {
    name: 'Security Analyst',
    role: 'AppSec Engineer',
    icon: 'ph-lock-key',
    description: 'Runs bandit, npm audit, and Trivy scans. Blocks on OWASP Top 10 violations.',
    tools: ['bandit', 'npm-audit', 'trivy', 'shell'],
  },
  'Database Engineer': {
    name: 'Database Engineer',
    role: 'Data Layer Engineer',
    icon: 'ph-database',
    description: 'Designs schemas, writes Alembic migrations, optimizes queries. Only parameterized SQL.',
    tools: ['alembic', 'sql', 'filesystem', 'shell'],
  },
}
