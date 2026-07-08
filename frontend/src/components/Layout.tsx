import { Outlet } from 'react-router-dom'
import { SelectedAccountProvider, useSelectedAccount } from '../hooks/useSelectedAccount'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

function LayoutInner() {
  const { selectedAccountId, selectAccount } = useSelectedAccount()

  return (
    <div className="flex h-screen overflow-hidden relative">
      <Sidebar />
      <div className="flex-1 ml-[260px] flex flex-col min-w-0 relative">
        <TopBar selectedAccountId={selectedAccountId} onAccountChange={selectAccount} />
        <main className="flex-1 overflow-y-auto p-6 relative z-10">
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
