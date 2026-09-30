import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    {/* Route changes render synchronously so the next test step never acts on the previous page. */}
    <BrowserRouter unstable_useTransitions={false}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
