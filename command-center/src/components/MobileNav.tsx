import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/',        icon: 'ph-squares-four',  label: 'Dashboard' },
  { to: '/agents',  icon: 'ph-users-three',   label: 'Agents'    },
  { to: '/logs',    icon: 'ph-terminal',      label: 'Logs'      },
  { to: '/history', icon: 'ph-clock-counter-clockwise', label: 'History' },
  { to: '/settings', icon: 'ph-gear',         label: 'Settings'  },
]

export function MobileNav() {
  return (
    <nav className="lg:hidden fixed bottom-0 inset-x-0 bg-brand-800 border-t border-slate-700/60 safe-bottom z-50">
      <div className="flex">
        {navItems.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex-1 flex flex-col items-center gap-0.5 py-2.5 min-h-[56px] transition-colors ${
                isActive
                  ? 'text-blue-400'
                  : 'text-slate-500 hover:text-slate-300 active:text-slate-200'
              }`
            }
          >
            <i className={`ph ${icon} text-[22px] leading-none`} />
            <span className="text-[10px] font-medium leading-none">{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
