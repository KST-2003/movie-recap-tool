import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import '@fontsource/poppins/400.css'
import '@fontsource/poppins/500.css'
import '@fontsource/poppins/600.css'
import '@fontsource/poppins/700.css'
import './index.css'
import { LangProvider } from './i18n.jsx'
import { initOta, initSafeArea, isNative } from './native.js'

if (isNative) {   // the app is not a page to pinch-zoom: lock the scale so a focused field can never leave the screen zoomed in
  document.querySelector('meta[name=viewport]')?.setAttribute('content', 'width=device-width, initial-scale=1.0, maximum-scale=1.0, viewport-fit=cover');
}
initSafeArea()
initOta()   // phone app only: tells the OTA updater this bundle started fine

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <LangProvider><App /></LangProvider>
  </React.StrictMode>,
)
