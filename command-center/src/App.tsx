import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Header } from '@/components/Header'
import { MobileNav } from '@/components/MobileNav'
import { Sidebar } from '@/components/Sidebar'
import { Dashboard } from '@/pages/Dashboard'
import { AgentsPage } from '@/pages/AgentsPage'
import { LogsPage } from '@/pages/LogsPage'
import { HistoryPage } from '@/pages/HistoryPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { AgentDetailPage } from '@/pages/AgentDetailPage'
import { useAgentState } from '@/hooks/useAgentState'

// Phosphor Icons web font — loaded via CDN in index.html so icon classes work globally
export default function App() {
  const { state, wsStatus } = useAgentState()

  return (
    <BrowserRouter>
      <div className="flex flex-col h-full">
        {/* Top header */}
        <Header wsStatus={wsStatus} />

        {/* Body: sidebar (desktop) + main content */}
        <div className="flex flex-1 min-h-0">
          <Sidebar />

          {/* Main scrollable area with bottom padding for mobile nav */}
          <main className="flex-1 min-w-0 overflow-y-auto lg:overflow-hidden p-4 pb-[80px] lg:pb-4 lg:flex lg:flex-col">
            <Routes>
              <Route path="/"        element={<Dashboard  state={state} />} />
              <Route path="/agents"  element={<AgentsPage state={state} />} />
              <Route path="/logs"    element={<LogsPage   state={state} />} />
              <Route path="/history" element={<HistoryPage state={state} />} />
              <Route path="/settings"      element={<SettingsPage    state={state} />} />
              <Route path="/agents/:name" element={<AgentDetailPage state={state} />} />
            </Routes>
          </main>
        </div>

        {/* Bottom nav — mobile only */}
        <MobileNav />
      </div>
    </BrowserRouter>
  )
}
