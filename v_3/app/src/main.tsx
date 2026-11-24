import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@nexfluid/foundation/tokens.css'
import '@nexfluid/components/styles.css'
import './caja.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
