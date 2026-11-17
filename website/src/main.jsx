import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import '@fontsource/poppins/400.css';
import '@fontsource/poppins/500.css';
import '@fontsource/poppins/600.css';
import '@fontsource/fredoka/500.css';
import '@fontsource/fredoka/600.css';
import '@fontsource/noto-sans-myanmar/400.css';
import '@fontsource/noto-sans-myanmar/600.css';
import './index.css';
import { LangProvider } from './lang.jsx';
import App from './App.jsx';

createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <LangProvider>
      <App />
    </LangProvider>
  </BrowserRouter>,
);
