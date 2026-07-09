import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import BlockchainBackground from './components/BlockchainBackground'
import ClickRipple from './components/ClickRipple'
import VideoBackground from './components/VideoBackground'
import { PerformanceModeProvider } from './hooks/usePerformanceMode'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PerformanceModeProvider>
      <VideoBackground />
      <BlockchainBackground />
      <ClickRipple />
      <App />
    </PerformanceModeProvider>
  </React.StrictMode>,
)
