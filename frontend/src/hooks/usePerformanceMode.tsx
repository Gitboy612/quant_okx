import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

interface PerformanceModeContextType {
  performanceMode: boolean
  togglePerformanceMode: () => void
}

const PerformanceModeContext = createContext<PerformanceModeContextType>({
  performanceMode: false,
  togglePerformanceMode: () => {},
})

const STORAGE_KEY = 'qstudio-performance-mode'

export function PerformanceModeProvider({ children }: { children: ReactNode }) {
  const [performanceMode, setPerformanceMode] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(performanceMode))
    } catch {}
    if (performanceMode) {
      document.body.classList.add('performance-mode')
    } else {
      document.body.classList.remove('performance-mode')
    }
  }, [performanceMode])

  const togglePerformanceMode = useCallback(() => {
    setPerformanceMode((prev) => !prev)
  }, [])

  return (
    <PerformanceModeContext.Provider value={{ performanceMode, togglePerformanceMode }}>
      {children}
    </PerformanceModeContext.Provider>
  )
}

export function usePerformanceMode() {
  return useContext(PerformanceModeContext)
}
