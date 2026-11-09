import React from 'react'
import ReactDOM from 'react-dom/client'
import axios from 'axios'
import App from './App.jsx'
import './index.css'
import { LangProvider } from './i18n.jsx'

// every admin page calls relative /api/... paths; this is the one place that says where the API is
axios.defaults.baseURL = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <LangProvider><App /></LangProvider>
  </React.StrictMode>,
)
