import { ReactNode } from 'react';
import './Layout.css';

interface LayoutProps {
  children: ReactNode;
  currentPage: 'voice' | 'chat';
}

export default function Layout({ children, currentPage }: LayoutProps) {
  const navigateTo = (page: 'voice' | 'chat') => {
    if (page === 'chat') {
      window.location.href = '/chat';
    } else {
      window.location.href = '/';
    }
  };

  return (
    <div className="layout">
      <header className="layout-header">
        <div className="layout-header-content">
          <h1 className="layout-title">🗣️ Vak Assistant</h1>
          <nav className="layout-nav">
            <button
              className={`nav-button ${currentPage === 'voice' ? 'active' : ''}`}
              onClick={() => navigateTo('voice')}
            >
              🎙️ Voice
            </button>
            <button
              className={`nav-button ${currentPage === 'chat' ? 'active' : ''}`}
              onClick={() => navigateTo('chat')}
            >
              💬 Chat
            </button>
          </nav>
        </div>
      </header>
      <main className="layout-main">
        {children}
      </main>
    </div>
  );
}
