import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/',        icon: 'ph-squares-four',            label: 'Dashboard' },
  { to: '/agents',  icon: 'ph-users-three',             label: 'Agents'    },
  { to: '/logs',    icon: 'ph-terminal',                label: 'Logs'      },
  { to: '/history', icon: 'ph-clock-counter-clockwise', label: 'History'   },
  { to: '/settings', icon: 'ph-gear',                   label: 'Settings'  },
]

export function Sidebar() {
  return (
    <aside className="hidden lg:flex flex-col w-56 bg-brand-800 border-r border-slate-700/60 shrink-0 py-4">
      <p className="text-[10px] text-slate-600 uppercase tracking-widest font-semibold px-4 mb-2">
        Navigation
      </p>
      <nav className="flex flex-col gap-1 px-2">
        {navItems.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/40'
              }`
            }
          >
            <i className={`ph ${icon} text-lg leading-none`} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
