import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Layout from './Layout';
import './ChatPage.css';

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: Date;
};

type EndpointType = 'local' | 'alb';

const DEFAULT_LOCAL_URL = 'http://localhost:8080/chat';
const DEFAULT_ALB_URL = 'https://vak.tutzi.ai/chat';

export default function ChatPage() {
  const [endpointType, setEndpointType] = useState<EndpointType>('local');
  const [endpoint, setEndpoint] = useState(DEFAULT_LOCAL_URL);
  const [businessNumber, setBusinessNumber] = useState('+15104054454');
  const [customerNumber, setCustomerNumber] = useState('+15105796565');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [showConfig, setShowConfig] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Check authentication status on mount
  useEffect(() => {
    // For ALB with Cognito, check if we have a session cookie
    if (endpointType === 'alb') {
      // Try a simple request to see if authenticated
      checkAuthStatus();
    }
  }, [endpointType]);

  const checkAuthStatus = async () => {
    if (endpointType !== 'alb') return;

    try {
      // Make a request to check auth - Cognito will redirect if not authenticated
      const response = await fetch(endpoint, {
        method: 'OPTIONS',
        credentials: 'include',
      });
      setIsAuthenticated(response.ok);
    } catch {
      setIsAuthenticated(false);
    }
  };

  const handleEndpointTypeChange = (type: EndpointType) => {
    setEndpointType(type);
    if (type === 'local') {
      setEndpoint(DEFAULT_LOCAL_URL);
      setIsAuthenticated(true); // Local doesn't need auth
    } else {
      setEndpoint(DEFAULT_ALB_URL);
      setIsAuthenticated(false);
    }
  };

  const startCognitoAuth = () => {
    // Open the chat endpoint in a new tab to trigger Cognito auth flow
    // After auth, the user will be redirected back with a session cookie
    window.open(endpoint, '_blank', 'noopener');
  };

  const generateMessageId = () => {
    return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  };

  const sendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed || isSending) {
      return;
    }
    setError(null);
    setIsSending(true);
    setInput('');

    const userMessage: ChatMessage = {
      id: generateMessageId(),
      role: 'user',
      text: trimmed,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);

    try {
      const requestBody: { message: string; business_number?: string; customer_number?: string } = {
        message: trimmed
      };
      if (businessNumber.trim()) {
        requestBody.business_number = businessNumber.trim();
      }
      if (customerNumber.trim()) {
        requestBody.customer_number = customerNumber.trim();
      }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: endpointType === 'alb' ? 'include' : 'omit',
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const text = await response.text();
        if (response.status === 401 || response.status === 403) {
          setIsAuthenticated(false);
          throw new Error('Authentication required. Please authenticate first.');
        }
        throw new Error(text || `Request failed (${response.status})`);
      }

      const data = await response.json();
      const reply = typeof data.reply === 'string' ? data.reply : '';

      const assistantMessage: ChatMessage = {
        id: generateMessageId(),
        role: 'assistant',
        text: reply || '(no response)',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
      setIsAuthenticated(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Request failed';
      setError(message);
      const errorMessage: ChatMessage = {
        id: generateMessageId(),
        role: 'assistant',
        text: 'Sorry, something went wrong. Please try again.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearConversation = () => {
    setMessages([]);
    setError(null);
  };

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <Layout currentPage="chat">
      <div className="chat-page">
        <div className="chat-container">
          {/* Configuration Panel */}
          <div className={`chat-config-panel ${showConfig ? 'expanded' : 'collapsed'}`}>
            <button
              className="config-toggle"
              onClick={() => setShowConfig(!showConfig)}
              aria-label={showConfig ? 'Hide settings' : 'Show settings'}
            >
              <span className="config-toggle-icon">{showConfig ? '▼' : '▶'}</span>
              <span className="config-toggle-text">Settings</span>
            </button>

            {showConfig && (
              <div className="config-content">
                {/* Endpoint Selection */}
                <div className="config-section">
                  <label className="config-label">Endpoint</label>
                  <div className="endpoint-buttons">
                    <button
                      className={`endpoint-btn ${endpointType === 'local' ? 'active' : ''}`}
                      onClick={() => handleEndpointTypeChange('local')}
                    >
                      <span className="endpoint-icon">🏠</span>
                      <span className="endpoint-text">Local</span>
                    </button>
                    <button
                      className={`endpoint-btn ${endpointType === 'alb' ? 'active' : ''}`}
                      onClick={() => handleEndpointTypeChange('alb')}
                    >
                      <span className="endpoint-icon">☁️</span>
                      <span className="endpoint-text">Cloud (vak.tutzi.ai)</span>
                    </button>
                  </div>
                  <div className="endpoint-url">{endpoint}</div>
                </div>

                {/* Auth Button for ALB */}
                {endpointType === 'alb' && (
                  <div className="config-section">
                    <div className="auth-status">
                      <span className={`auth-indicator ${isAuthenticated ? 'authenticated' : 'unauthenticated'}`}>
                        {isAuthenticated ? '🔓 Authenticated' : '🔒 Not Authenticated'}
                      </span>
                      <button
                        className="auth-btn"
                        onClick={startCognitoAuth}
                      >
                        🔐 Authenticate
                      </button>
                    </div>
                  </div>
                )}

                {/* Business & Customer Numbers */}
                <div className="config-row">
                  <div className="config-field">
                    <label className="config-label" htmlFor="businessNumber">Business Number</label>
                    <input
                      id="businessNumber"
                      type="text"
                      value={businessNumber}
                      onChange={(e) => setBusinessNumber(e.target.value)}
                      placeholder="+15104054454"
                    />
                  </div>
                  <div className="config-field">
                    <label className="config-label" htmlFor="customerNumber">Customer Number</label>
                    <input
                      id="customerNumber"
                      type="text"
                      value={customerNumber}
                      onChange={(e) => setCustomerNumber(e.target.value)}
                      placeholder="+15105796565"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Messages Area */}
          <div className="chat-messages-container">
            {messages.length === 0 ? (
              <div className="chat-empty-state">
                <div className="empty-icon">💬</div>
                <h3>Start a Conversation</h3>
                <p>Ask Vak Assistant anything about appointments, availability, or services.</p>
                <div className="example-prompts">
                  <button onClick={() => setInput("What services do you offer?")}>
                    What services do you offer?
                  </button>
                  <button onClick={() => setInput("Do you have any availability this week?")}>
                    Do you have any availability this week?
                  </button>
                  <button onClick={() => setInput("I'd like to book an appointment")}>
                    I'd like to book an appointment
                  </button>
                </div>
              </div>
            ) : (
              <div className="chat-messages">
                {messages.map((msg) => (
                  <div key={msg.id} className={`message ${msg.role}`}>
                    <div className="message-avatar">
                      {msg.role === 'user' ? '👤' : '🤖'}
                    </div>
                    <div className="message-content">
                      <div className="message-header">
                        <span className="message-sender">
                          {msg.role === 'user' ? 'You' : 'Vak Assistant'}
                        </span>
                        <span className="message-time">{formatTime(msg.timestamp)}</span>
                      </div>
                      <div className="message-text">
                          {msg.role === 'assistant' ? (
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
                          ) : (
                            msg.text
                          )}
                        </div>
                    </div>
                  </div>
                ))}
                {isSending && (
                  <div className="message assistant">
                    <div className="message-avatar">🤖</div>
                    <div className="message-content">
                      <div className="message-header">
                        <span className="message-sender">Vak Assistant</span>
                      </div>
                      <div className="message-text typing">
                        <span className="typing-dot"></span>
                        <span className="typing-dot"></span>
                        <span className="typing-dot"></span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* Error Display */}
          {error && (
            <div className="chat-error">
              <span className="error-icon">⚠️</span>
              <span className="error-text">{error}</span>
              <button className="error-dismiss" onClick={() => setError(null)}>×</button>
            </div>
          )}

          {/* Input Area */}
          <div className="chat-input-container">
            <div className="chat-input-wrapper">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
                rows={1}
                disabled={isSending}
              />
              <div className="input-actions">
                {messages.length > 0 && (
                  <button
                    className="clear-btn"
                    onClick={clearConversation}
                    title="Clear conversation"
                  >
                    🗑️
                  </button>
                )}
                <button
                  className="send-btn"
                  onClick={sendMessage}
                  disabled={isSending || !input.trim()}
                >
                  {isSending ? (
                    <span className="sending-spinner"></span>
                  ) : (
                    '➤'
                  )}
                </button>
              </div>
            </div>
            <div className="input-hint">
              Press Enter to send • Shift+Enter for new line
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
