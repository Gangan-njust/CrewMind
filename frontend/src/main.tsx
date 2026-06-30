import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import 'katex/dist/katex.min.css'

const savedTheme = localStorage.getItem('crewmind-theme')
if (savedTheme === 'light' || savedTheme === 'dark') {
  document.documentElement.setAttribute('data-theme', savedTheme)
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
