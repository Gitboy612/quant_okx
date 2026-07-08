import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { getMe } from '../api/auth'
import type { User } from '../types'

interface AuthContextType {
  user: User | null
  loading: boolean
  login: (token: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  login: () => {},
  logout: () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = sessionStorage.getItem('token')
    if (!token) {
      setLoading(false)
      return
    }
    getMe()
      .then((res) => setUser(res.data))
      .catch(() => sessionStorage.removeItem('token'))
      .finally(() => setLoading(false))
  }, [])

  const login = async (token: string) => {
    sessionStorage.setItem('token', token)
    setLoading(true)
    try {
      const res = await getMe()
      setUser(res.data)
    } catch {
      sessionStorage.removeItem('token')
    } finally {
      setLoading(false)
    }
  }

  const logout = () => {
    sessionStorage.removeItem('token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

export type { User }
