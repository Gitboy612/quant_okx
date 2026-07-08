import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import BlockchainBackground from './components/BlockchainBackground'
import ClickRipple from './components/ClickRipple'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BlockchainBackground />
    <ClickRipple />
    <App />
  </React.StrictMode>,
)
