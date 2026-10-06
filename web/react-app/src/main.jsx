import React from 'react'
import { createRoot } from 'react-dom/client'
import mermaid from 'mermaid'
import App from './App.jsx'
import './index.css'

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'loose',
  themeVariables: {
    darkMode: true,
    background: '#080a10',
    primaryColor: '#1e3a8a',
    primaryTextColor: '#f1f4fb',
    primaryBorderColor: '#3b82f6',
    lineColor: '#60a5fa',
    secondaryColor: '#1e293b',
    tertiaryColor: '#0f172a',
  },
})

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
