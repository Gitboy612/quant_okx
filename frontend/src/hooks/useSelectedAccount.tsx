import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { listAccounts } from '../api/accounts'
import type { Account } from '../types'

interface SelectedAccountContextType {
  accounts: Account[]
  selectedAccountId: number | null
  selectAccount: (id: number | null) => void
}

const SelectedAccountContext = createContext<SelectedAccountContextType>({
  accounts: [],
  selectedAccountId: null,
  selectAccount: () => {},
})

export function SelectedAccountProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null)

  useEffect(() => {
    listAccounts().then((res) => {
      const accts: Account[] = res.data
      setAccounts(accts)
      if (accts.length > 0 && selectedAccountId === null) {
        setSelectedAccountId(accts[0].id)
      }
    }).catch(() => {})
  }, [])

  const selectAccount = (id: number | null) => {
    setSelectedAccountId(id)
  }

  return (
    <SelectedAccountContext.Provider value={{ accounts, selectedAccountId, selectAccount }}>
      {children}
    </SelectedAccountContext.Provider>
  )
}

export function useSelectedAccount() {
  return useContext(SelectedAccountContext)
}
