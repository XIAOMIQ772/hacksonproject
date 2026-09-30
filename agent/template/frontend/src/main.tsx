import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    {/* Commit route changes synchronously, so the next page is on screen as soon as a navigation is clicked. */}
    <BrowserRouter unstable_useTransitions={false}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
