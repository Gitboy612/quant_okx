import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { SelectedAccountProvider, useSelectedAccount } from '../hooks/useSelectedAccount'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

function LayoutInner() {
  const { selectedAccountId, selectAccount } = useSelectedAccount()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden relative">
      <Sidebar
        mobileOpen={mobileSidebarOpen}
        onClose={() => setMobileSidebarOpen(false)}
      />
      <div className="flex-1 md:ml-[260px] flex flex-col min-w-0 relative">
        <TopBar
          selectedAccountId={selectedAccountId}
          onAccountChange={selectAccount}
          onMenuClick={() => setMobileSidebarOpen(true)}
        />
        <main className="flex-1 overflow-y-auto p-4 md:p-6 relative z-10">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default function Layout() {
  return (
    <SelectedAccountProvider>
      <LayoutInner />
    </SelectedAccountProvider>
  )
}
