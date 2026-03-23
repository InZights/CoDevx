import { useState } from 'react'
import type { SystemState } from '@/types'

interface SettingsSection {
  title: string
  icon: string
  children: React.ReactNode
}

function Section({ title, icon, children }: SettingsSection) {
  return (
    <div className="bg-brand-800 rounded-xl border border-slate-700/60 p-4">
      <h3 className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-2 mb-4">
        <i className={`ph ${icon}`} />
        {title}
      </h3>
      {children}
    </div>
  )
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-700/40 last:border-0">
      <span className="text-sm text-slate-400">{label}</span>
      <span className={`text-sm text-slate-300 ${mono ? 'font-mono' : 'font-medium'}`}>{value}</span>
    </div>
  )
}

function Badge({ label, active }: { label: string; active: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${
      active
        ? 'bg-emerald-900/40 text-emerald-400 border border-emerald-500/30'
        : 'bg-slate-800 text-slate-500 border border-slate-700/50'
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-emerald-400' : 'bg-slate-600'}`} />
      {label}
    </span>
  )
}

interface Props {
  state?: SystemState
}

export function SettingsPage({ state }: Props) {
  const [backendUrl, setBackendUrl] = useState(
    () => localStorage.getItem('backendUrl') ?? (import.meta.env.VITE_BACKEND_URL as string ?? 'http://localhost:8000'),
  )
  const [saved, setSaved] = useState(false)

  function handleSave() {
    localStorage.setItem('backendUrl', backendUrl)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const messaging = state?.messaging ?? 'discord'
  const llmEnabled = state?.llm_enabled ?? false
  const gitEnabled = state?.git_enabled ?? false
  const zcEnabled       = state?.zeroclaw_enabled ?? false
  const realToolsEnabled  = state?.real_tools_enabled ?? false
  const dockerEnabled     = state?.docker_build_enabled ?? false
  const maxRetries        = state?.max_retries ?? 2
  const maxSubtasks       = state?.max_subtasks ?? 5
  const maxTokens         = state?.openai_max_tokens ?? 4000

  return (
    <div className="max-w-2xl space-y-4">

      {/* Connection */}
      <Section title="Connection" icon="ph-plug">
        <Row label="WebSocket Endpoint" value="/ws/state" mono />
        <Row label="REST Fallback" value="/api/state" mono />
        <Row label="Files API" value="/api/files/:taskId" mono />
        <Row label="WA Webhook" value="POST /webhook/whatsapp" mono />
        <Row label="ZC Webhook" value="POST /webhook/zeroclaw" mono />
        <div className="pt-3">
          <label className="block text-xs text-slate-500 mb-1.5">Backend URL (for LAN / mobile access)</label>
          <div className="flex gap-2">
            <input
              type="url"
              value={backendUrl}
              onChange={e => setBackendUrl(e.target.value)}
              className="flex-1 bg-slate-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-300 font-mono focus:outline-none focus:border-blue-500/50"
            />
            <button
              onClick={handleSave}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                saved
                  ? 'bg-emerald-600/30 text-emerald-400 border border-emerald-500/40'
                  : 'bg-blue-600 hover:bg-blue-500 text-white'
              }`}
            >
              {saved ? '✓ Saved' : 'Save'}
            </button>
          </div>
          <p className="text-[11px] text-slate-600 mt-1.5">
            On Android, replace <code className="text-slate-500">localhost</code> with your laptop's LAN IP or Tailscale address.
          </p>
        </div>
      </Section>

      {/* Messaging Provider */}
      <Section title="Messaging Provider" icon="ph-chats">
        <div className="flex items-center gap-3 py-2 border-b border-slate-700/40">
          <span className="text-sm text-slate-400 flex-1">Active Provider</span>
          <div className="flex gap-2 flex-wrap justify-end">
            <Badge label="Discord"   active={messaging === 'discord'   || messaging === 'both'} />
            <Badge label="WhatsApp" active={messaging === 'whatsapp' || messaging === 'both'} />
            <Badge label="ZeroClaw" active={messaging === 'zeroclaw' || zcEnabled} />
          </div>
        </div>
        <Row label="Set via" value="MESSAGING_PROVIDER in .env" mono />
        <Row label="Options" value="discord | whatsapp | both" mono />
        <p className="text-[11px] text-slate-600 mt-3">
          Set <code className="text-slate-500">MESSAGING_PROVIDER=both</code> to use Discord and WhatsApp simultaneously.
          Set <code className="text-slate-500">MESSAGING_PROVIDER=zeroclaw</code> to route all channels through ZeroClaw.
        </p>
      </Section>

      {/* ZeroClaw Gateway */}
      <Section title="ZeroClaw Gateway" icon="ph-robot">
        <div className="flex items-center gap-3 py-2 border-b border-slate-700/40">
          <span className="text-sm text-slate-400 flex-1">Status</span>
          <Badge label={zcEnabled ? 'Configured' : 'Not configured'} active={zcEnabled} />
        </div>
        <Row label="Project" value="zeroclaw-labs/zeroclaw (Rust, MIT/Apache 2)" />
        <Row label="Binary size" value="~8.8 MB — <5 MB RAM at runtime" />
        <Row label="Channels" value="Discord, WhatsApp, Telegram, Slack, Signal + 20 more" />
        <Row label="Gateway" value="ZEROCLAW_GATEWAY_URL (default: localhost:42617)" mono />
        <Row label="Webhook" value="POST /webhook/zeroclaw" mono />
        <Row label="Security" value="HMAC-SHA256 (ZEROCLAW_WEBHOOK_SECRET)" />
        <Row label="Autonomy" value="ReadOnly | Supervised (default) | Full" />
        <Row label="SOP file" value="zeroclaw.sop.yaml.example" mono />
        <div className="mt-3 p-3 bg-slate-900/40 rounded-lg border border-slate-700/40 space-y-1">
          <p className="text-[11px] text-slate-500 font-semibold">Setup (4 steps):</p>
          <p className="text-[11px] text-slate-600">1. Install: <code className="text-slate-500">curl -fsSL https://zeroclawlabs.ai/install.sh | bash</code></p>
          <p className="text-[11px] text-slate-600">2. Onboard: <code className="text-slate-500">zeroclaw onboard</code></p>
          <p className="text-[11px] text-slate-600">3. Copy config + SOP examples → ~/.zeroclaw/ and edit</p>
          <p className="text-[11px] text-slate-600">4. Set env: <code className="text-slate-500">MESSAGING_PROVIDER=zeroclaw</code> + <code className="text-slate-500">ZEROCLAW_WEBHOOK_SECRET</code></p>
        </div>
      </Section>

      {/* Discord */}
      <Section title="Discord Integration" icon="ph-discord-logo">
        <Badge label={messaging === 'discord' || messaging === 'both' ? 'Active' : 'Inactive'}
               active={messaging === 'discord' || messaging === 'both'} />
        <div className="mt-3">
          <Row label="Order Command" value="!order <task>" mono />
          <Row label="Plan Approval" value="#plans channel (buttons)" />
          <Row label="Activity Mirror" value="#activity-log (read-only)" />
          <Row label="Report Destination" value="#reports channel" />
          <Row label="Who can approve" value="MANAGER_DISCORD_ID only" />
        </div>
      </Section>

      {/* WhatsApp */}
      <Section title="WhatsApp Integration" icon="ph-whatsapp-logo">
        <Badge label={messaging === 'whatsapp' || messaging === 'both' ? 'Active' : 'Inactive'}
               active={messaging === 'whatsapp' || messaging === 'both'} />
        <div className="mt-3">
          <Row label="Provider" value="Twilio WhatsApp API" />
          <Row label="Order Command" value="order <task>" mono />
          <Row label="Approve" value="Reply: approve" mono />
          <Row label="Reject" value="Reply: reject" mono />
          <Row label="Webhook endpoint" value="POST /webhook/whatsapp" mono />
        </div>
        <div className="mt-3 p-3 bg-slate-900/40 rounded-lg border border-slate-700/40 space-y-1">
          <p className="text-[11px] text-slate-500 font-semibold">Setup steps:</p>
          <p className="text-[11px] text-slate-600">1. Create a Twilio account → enable WhatsApp sandbox</p>
          <p className="text-[11px] text-slate-600">2. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, MANAGER_WHATSAPP in .env</p>
          <p className="text-[11px] text-slate-600">3. Expose backend with ngrok: <code className="text-slate-500">ngrok http 8000</code></p>
          <p className="text-[11px] text-slate-600">4. Set Twilio sandbox webhook → <code className="text-slate-500">https://&lt;ngrok&gt;/webhook/whatsapp</code></p>
        </div>
      </Section>

      {/* LLM Engine */}
      <Section title="LLM Engine" icon="ph-brain">
        <div className="flex items-center gap-3 py-2 border-b border-slate-700/40">
          <span className="text-sm text-slate-400 flex-1">Status</span>
          <Badge label={llmEnabled ? 'Live LLM' : 'Simulated'} active={llmEnabled} />
        </div>
        <Row label="Provider" value="OpenAI API (or compatible)" />
        <Row label="Model" value="OPENAI_MODEL in .env" mono />
        <Row label="Supports" value="GPT-4o, Azure OpenAI, local endpoints" />
        <Row label="System prompts" value="8 role-specific prompts (one per agent)" />
        <Row label="Max tokens" value="OPENAI_MAX_TOKENS (default: 4 000)" mono />
        <Row label="Temperature" value="0.3 (focused, deterministic)" />
        <p className="text-[11px] text-slate-600 mt-3">
          Without OPENAI_API_KEY the pipeline runs in simulation mode — agents produce placeholder output files.
          Set OPENAI_BASE_URL to use Azure OpenAI or a local Ollama endpoint.
        </p>
      </Section>

      {/* Git Integration */}
      <Section title="Git Integration" icon="ph-git-branch">
        <div className="flex items-center gap-3 py-2 border-b border-slate-700/40">
          <span className="text-sm text-slate-400 flex-1">GitHub PR</span>
          <Badge label={gitEnabled ? 'Configured' : 'Local only'} active={gitEnabled} />
        </div>
        <Row label="Workspace" value="GIT_WORKSPACE in .env (default: ./workspace)" mono />
        <Row label="Branch naming" value="feat/<task-id>" mono />
        <Row label="Auto-commit" value="After every completed pipeline" />
        <Row label="PR creation" value="Requires GITHUB_TOKEN + GITHUB_REPO" />
        <Row label="Push target" value="origin/main" mono />
        <p className="text-[11px] text-slate-600 mt-3">
          Set GITHUB_TOKEN (repo scope) and GITHUB_REPO (owner/repo) to enable automatic PR creation on task completion.
        </p>
      </Section>

      {/* Agent Squad */}
      <Section title="Agent Squad" icon="ph-users-three">
        <Row label="Total Agents" value="8" />
        <Row label="Coverage Gate" value="≥ 80% required" />
        <Row label="Security Gate" value="No CRITICAL/HIGH CVEs" />
        <Row label="PR Required" value="Yes — before merge" />
        <Row label="Config file" value="zeroclaw_squad.yaml" mono />
      </Section>

      {/* Mobile & PWA */}
      <Section title="Mobile & PWA" icon="ph-device-mobile">
        <Row label="PWA Support" value="Enabled (Android)" />
        <Row label="Offline Shell" value="Service Worker active" />
        <Row label="Install Hint" value="Chrome → ⋮ → Add to Home Screen" />
        <Row label="App Name" value="CmdCenter" />
      </Section>

      {/* Pipeline Engine */}
      <Section title="Pipeline Engine (v4.0)" icon="ph-gear-six">
        <div className="flex items-center gap-3 py-2 border-b border-slate-700/40">
          <span className="text-sm text-slate-400 flex-1">Real Tool Execution</span>
          <Badge label={realToolsEnabled ? 'pytest + bandit + npm-audit' : 'Disabled'} active={realToolsEnabled} />
        </div>
        <div className="flex items-center gap-3 py-2 border-b border-slate-700/40">
          <span className="text-sm text-slate-400 flex-1">Docker Build</span>
          <Badge label={dockerEnabled ? 'Enabled' : 'Disabled'} active={dockerEnabled} />
        </div>
        <Row label="QA / Security Retries" value={`${maxRetries} attempts per gate`} />
        <Row label="Max Task Phases" value={`${maxSubtasks} (task decomposition)`} />
        <Row label="Max Tokens / Agent" value={`${maxTokens.toLocaleString()} per LLM call`} />
        <Row label="Memory (cross-task)" value="SQLite agent_memory table" mono />
        <Row label="QA coverage gate" value="≥ 80% required to pass" />
        <Row label="Security gate" value="No CRITICAL/HIGH CVEs to pass" />
        <p className="text-[11px] text-slate-600 mt-3">
          Set <code className="text-slate-500">ENABLE_REAL_TOOLS=true</code> to run pytest / bandit / npm-audit during pipeline.
          Set <code className="text-slate-500">DOCKER_BUILD=true</code> to build a Docker image after DevOps generates a Dockerfile.
        </p>
      </Section>

      {/* Storage */}
      <Section title="Persistent Storage" icon="ph-database">
        <Row label="Engine" value="SQLite (aiosqlite)" />
        <Row label="Database file" value="DB_PATH in .env (default: ./agent_mesh.db)" mono />
        <Row label="Tables" value="logs, task_history, generated_files, agent_memory" mono />
        <Row label="Agent memory" value="Keyword-searched, injected into each Architect call" />
        <Row label="Task retention" value="Last 50 tasks loaded on boot" />
        <Row label="Files API" value="GET /api/files/:taskId" mono />
      </Section>

      {/* About */}
      <Section title="About" icon="ph-info">
        <Row label="Version" value="4.0.0" />
        <Row label="Built With" value="React 19 + Vite + Tailwind CSS" />
        <Row label="Backend" value="FastAPI + WebSocket + SQLite" />
        <Row label="Messaging" value="Discord + WhatsApp (Twilio) + ZeroClaw gateway" />
        <Row label="Pipeline" value="Iterative loops, real tool execution, agent memory" />
        <Row label="LLM" value="OpenAI API (GPT-4o / Azure / compatible)" />
        <Row label="Git" value="subprocess git + GitHub REST API" />
        <Row label="ZeroClaw" value="github.com/zeroclaw-labs/zeroclaw" mono />
      </Section>

    </div>
  )
}

