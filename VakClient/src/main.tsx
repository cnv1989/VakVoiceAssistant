import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import ChatPage from './ChatPage';
import './index.css';

const pathname = window.location.pathname;
const Root = pathname.startsWith('/chat') ? ChatPage : App;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
