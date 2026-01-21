import { useState } from 'react';
import Layout from './Layout';
import './ChatPage.css';

type ChatMessage = {
  role: 'user' | 'assistant';
  text: string;
};

const defaultChatUrl = import.meta.env.VITE_CHAT_URL || 'http://localhost:8080/chat';

export default function ChatPage() {
  const [endpoint, setEndpoint] = useState(defaultChatUrl);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed || isSending) {
      return;
    }
    setError(null);
    setIsSending(true);
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }]);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Request failed (${response.status})`);
      }
      const data = await response.json();
      const reply = typeof data.reply === 'string' ? data.reply : '';
      setMessages((prev) => [...prev, { role: 'assistant', text: reply || '(no response)' }]);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Request failed';
      setError(message);
      setMessages((prev) => [...prev, { role: 'assistant', text: 'Sorry, something went wrong.' }]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Layout currentPage="chat">
      <div className="chat-page">
        <div className="container">

          <section className="chat-config">
            <label>
              Endpoint
              <input
                type="text"
                value={endpoint}
                onChange={(event) => setEndpoint(event.target.value)}
                placeholder="http://localhost:8080/chat"
              />
            </label>
            <span className="chat-status">{isSending ? 'Sending...' : 'Ready'}</span>
          </section>

          <section className="chat-messages">
            {messages.length === 0 ? (
              <div className="chat-empty">Start a conversation to test chat responses.</div>
            ) : (
              messages.map((msg, index) => (
                <div key={`${msg.role}-${index}`} className={`chat-bubble ${msg.role}`}>
                  <span className="chat-role">{msg.role === 'user' ? 'You' : 'Assistant'}</span>
                  <p>{msg.text}</p>
                </div>
              ))
            )}
          </section>

          {error && <div className="chat-error">{error}</div>}

          <section className="chat-input">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask something..."
              rows={3}
            />
            <button type="button" onClick={sendMessage} disabled={isSending}>
              Send
            </button>
          </section>
        </div>
      </div>
    </Layout>
  );
}
