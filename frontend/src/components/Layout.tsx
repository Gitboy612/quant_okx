import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

export default function Layout() {
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null)

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 ml-60 flex flex-col min-w-0">
        <TopBar selectedAccountId={selectedAccountId} onAccountChange={setSelectedAccountId} />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
