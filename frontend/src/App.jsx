import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

function App() {
  const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
  
  const [token, setToken] = useState(localStorage.getItem('token'))
  const [userEmail, setUserEmail] = useState(localStorage.getItem('userEmail'))
  const [authMode, setAuthMode] = useState('login')
  const [authError, setAuthError] = useState('')
  
  const [viewMode, setViewMode] = useState('chat') 
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [chats, setChats] = useState([])
  const [activeChat, setActiveChat] = useState(null)
  const [messages, setMessages] = useState([
    { type: 'ai', text: 'Welcome to ContextIQ. To get started, upload a document or select an existing chat.', sources: [] }
  ])
  const [input, setInput] = useState('')
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploadingFile, setUploadingFile] = useState(null)
  const [summarizing, setSummarizing] = useState(false)
  
  const [deleteModal, setDeleteModal] = useState({ show: false, type: '', id: null, name: '' })

  const fileInputRef = useRef(null)
  const chatEndRef = useRef(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  useEffect(() => {
    if (token) {
      fetchChats()
      fetchSources()
    }
  }, [token])

  // Poll for document status if any are still indexing
  useEffect(() => {
    const hasUnindexed = sources.some(s => !s.indexed) || uploadingFile
    if (hasUnindexed && token) {
      const interval = setInterval(fetchSources, 5000)
      return () => clearInterval(interval)
    }
  }, [sources, uploadingFile, token])

  const fetchChats = async () => {
    try {
      const response = await fetch(`${API_BASE}/chats`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (response.ok) {
        const data = await response.json()
        setChats(data.chats)
      }
    } catch (error) { console.error(error) }
  }

  const fetchSources = async () => {
    try {
      const response = await fetch(`${API_BASE}/documents`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (response.ok) {
        const data = await response.json()
        setSources(data.documents)
      }
    } catch (error) { console.error(error) }
  }

  const handleAuth = async (email, password) => {
    setAuthError('')
    if (!email || !password) {
      setAuthError('Please fill in all fields')
      return
    }

    const endpoint = authMode === 'login' ? 'login' : 'register'
    try {
      const formData = new URLSearchParams()
      formData.append('username', email)
      formData.append('password', password)

      const response = await fetch(`${API_BASE}/${endpoint}`, {
        method: 'POST',
        headers: endpoint === 'login' ? { 'Content-Type': 'application/x-www-form-urlencoded' } : { 'Content-Type': 'application/json' },
        body: endpoint === 'login' ? formData : JSON.stringify({ email, password })
      })

      const data = await response.json()
      if (response.ok) {
        if (endpoint === 'login') {
          localStorage.setItem('token', data.access_token)
          localStorage.setItem('userEmail', email)
          setToken(data.access_token)
          setUserEmail(email)
        } else {
          setAuthMode('login')
          setAuthError('Registration successful! Please sign in.')
        }
      } else { 
        setAuthError(data.detail || 'Authentication failed') 
      }
    } catch (error) { 
      setAuthError('Server connection failed')
      console.error(error) 
    }
  }

  const handleLogout = () => {
    localStorage.clear()
    setToken(null)
    setUserEmail(null)
    setViewMode('chat')
    setMessages([{ type: 'ai', text: 'Welcome to ContextIQ.', sources: [] }])
    setChats([]); setSources([]); setActiveChat(null)
  }

  const handleNewChat = async () => {
    try {
      const response = await fetch(`${API_BASE}/chats`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ title: 'New Chat' })
      })
      if (response.ok) {
        const newChat = await response.json()
        setChats(prev => [newChat, ...prev])
        selectChat(newChat)
        if (window.innerWidth < 768) setSidebarOpen(false)
      }
    } catch (error) { console.error(error) }
  }

  const selectChat = async (chat) => {
    setViewMode('chat')
    setActiveChat(chat)
    if (window.innerWidth < 768) setSidebarOpen(false)
    setMessages([{ type: 'ai', text: `Loading ${chat.title}...`, sources: [] }])
    try {
      const response = await fetch(`${API_BASE}/chats/${chat.id}/messages`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (response.ok) {
        const data = await response.json()
        setMessages(data.messages.length > 0 ? data.messages.map(m => ({
          type: m.role === 'user' ? 'user' : 'ai',
          text: m.content
        })) : [{ type: 'ai', text: 'New chat started. Ask anything about your sources!', sources: [] }])
      }
    } catch (error) { console.error(error) }
  }

  const confirmDelete = () => {
    if (deleteModal.type === 'chat') executeDeleteChat(deleteModal.id)
    else executeDeleteSource(deleteModal.name)
    setDeleteModal({ show: false, type: '', id: null, name: '' })
  }

  const executeDeleteChat = async (chatId) => {
    try {
      const res = await fetch(`${API_BASE}/chats/${chatId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) {
        setChats(prev => prev.filter(c => c.id !== chatId))
        if (activeChat?.id === chatId) setActiveChat(null)
      }
    } catch (error) { console.error(error) }
  }

  const executeDeleteSource = async (filename) => {
    try {
      const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) setSources(prev => prev.filter(s => s.name !== filename))
    } catch (error) { console.error(error) }
  }

  const handleSend = async () => {
    if (!input.trim() || !activeChat || loading) return
    const userMsg = { type: 'user', text: input }
    setMessages(prev => [...prev, userMsg])
    const currentInput = input; setInput('')
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/query?chat_id=${activeChat.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ prompt: currentInput })
      })
      if (res.ok) {
        const data = await res.json()
        setMessages(prev => [...prev, { type: 'ai', text: data.answer || 'No response received.' }])
        if (data.new_title) {
          setChats(prev => prev.map(c => c.id === activeChat.id ? { ...c, title: data.new_title } : c))
          setActiveChat(prev => (prev?.id === activeChat.id ? { ...prev, title: data.new_title } : prev))
        }
      } else {
        const errorData = await res.json()
        setMessages(prev => [...prev, { type: 'ai', text: `Error: ${errorData.detail || 'Failed to get response'}` }])
      }
    } catch (error) { 
      setMessages(prev => [...prev, { type: 'ai', text: 'Connection error.' }])
    } finally { setLoading(false) }
  }

  const handleSummarize = async (filename) => {
    if (summarizing) return
    setSummarizing(true)
    try {
      const res = await fetch(`${API_BASE}/summary?file_name=${encodeURIComponent(filename)}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) {
        const data = await res.json()
        // If we have an active chat, add the summary there. If not, create one.
        let chatToUse = activeChat
        if (!chatToUse) {
          const chatRes = await fetch(`${API_BASE}/chats`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ title: `Summary: ${filename}` })
          })
          if (chatRes.ok) {
            chatToUse = await chatRes.json()
            setChats(prev => [chatToUse, ...prev])
            setActiveChat(chatToUse)
          }
        }
        
        setMessages(prev => [...prev, { type: 'ai', text: `### 📄 Summary of ${filename}\n\n${data.summary}` }])
        setViewMode('chat')
      } else {
        alert("Failed to generate summary. Make sure the document is fully indexed.")
      }
    } catch (error) { 
      console.error(error)
    } finally { setSummarizing(false) }
  }

  const handleFileUpload = async (e) => {
    const file = e.target.files[0]; if (!file) return
    setUploadingFile({ name: file.name })
    const formData = new FormData(); formData.append('file', file)
    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      })
      if (res.ok) fetchSources()
    } catch (error) { console.error(error) } finally { setUploadingFile(null) }
  }

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-logo">ContextIQ</div>
          <p className="auth-subtitle">Elevate your intelligence</p>
          {authError && <div className={`auth-message ${authError.includes('successful') ? 'success' : 'error'}`}>{authError}</div>}
          <input type="email" placeholder="Email" className="auth-input" id="authEmail" />
          <input type="password" placeholder="Password" className="auth-input" id="authPass" />
          <button className="auth-submit" onClick={() => handleAuth(document.getElementById('authEmail').value, document.getElementById('authPass').value)}>
            {authMode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
          <div className="auth-switch" onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(''); }}>
            {authMode === 'login' ? "Don't have an account? Sign up" : "Already have an account? Sign in"}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={`app-container ${sidebarOpen ? 'sidebar-open' : ''}`}>
      {deleteModal.show && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Confirm Deletion</h3>
            <p>Are you sure you want to delete <strong>{deleteModal.name}</strong>?</p>
            <div className="modal-actions">
              <button className="cancel-btn" onClick={() => setDeleteModal({ ...deleteModal, show: false })}>Cancel</button>
              <button className="confirm-btn" onClick={confirmDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}

      <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)}></div>

      <div className={`sidebar ${sidebarOpen ? 'visible' : ''}`}>
        <div className="sidebar-header">
          <div className="sidebar-title" onClick={() => { setViewMode('chat'); setSidebarOpen(false); }} style={{ cursor: 'pointer' }}>
            <img src="https://res.cloudinary.com/dcyedb0sm/image/upload/v1778056203/contextiq_logo_li8tdr.svg" style={{width: "100%", height: "100%"}} alt="Logo" />
          </div>
          <button className="mobile-close-btn" onClick={() => setSidebarOpen(false)}>✕</button>
        </div>
        
        <div className="sidebar-section">
          <div className="sidebar-section-header"><span>Sources</span></div>
          <button className="manage-sources-btn" onClick={() => { setViewMode('sources'); if (window.innerWidth < 768) setSidebarOpen(false); }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
            Manage Sources
          </button>
        </div>

        <div className="sidebar-section history-section">
          <div className="sidebar-section-header">
            <span>Recent Chats</span>
            <button className="add-btn" onClick={handleNewChat}>+</button>
          </div>
          <div className="history-list premium-scroll">
            {chats.map(c => (
              <div key={c.id} className={`history-item ${activeChat?.id === c.id && viewMode === 'chat' ? 'active' : ''}`} onClick={() => selectChat(c)}>
                <div className="history-title">{c.title}</div>
                <button className="delete-btn" onClick={(e) => { e.stopPropagation(); setDeleteModal({ show: true, type: 'chat', id: c.id, name: c.title }) }}>🗑️</button>
              </div>
            ))}
          </div>
        </div>

        <div className="user-profile-section">
          <div className="user-avatar">{userEmail?.charAt(0).toUpperCase()}</div>
          <div className="user-details">
            <div className="user-name-display">{userEmail?.split('@')[0]}</div>
            <button className="signout-link" onClick={handleLogout}>Sign out</button>
          </div>
        </div>
        <input type="file" ref={fileInputRef} style={{ display: 'none' }} onChange={handleFileUpload} />
      </div>

      <div className="main-content">
        <header className="header">
          <button className="mobile-menu-btn" onClick={() => setSidebarOpen(true)}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
          </button>
          <div className="chat-title">
            {viewMode === 'sources' ? 'Manage Sources' : (activeChat ? activeChat.title : 'ContextIQ')}
          </div>
        </header>

        {viewMode === 'sources' ? (
          <div className="sources-view-container premium-scroll">
            <div className="sources-grid-header">
              <h2>Your Documents</h2>
              <button className="primary-upload-btn" onClick={() => fileInputRef.current.click()}>+ Upload</button>
            </div>
            <div className="sources-grid">
              {sources.map((s, i) => (
                <div key={i} className="large-source-card">
                  <div className="source-card-icon">📄</div>
                  <div className="source-card-body">
                    <div className="source-card-name" title={s.name}>{s.name}</div>
                    <div className="source-card-meta">{s.indexed ? 'PDF Document' : '⚙️ Indexing...'}</div>
                  </div>
                  <div className="source-card-actions">
                    <button className="card-delete-btn" title="Delete" onClick={() => setDeleteModal({ show: true, type: 'source', name: s.name })}>🗑️</button>
                  </div>
                </div>
              ))}
              {uploadingFile && <div className="large-source-card uploading"><div className="source-card-icon loading-spin">⏳</div><div className="source-card-body"><div className="source-card-name">Uploading...</div></div></div>}
              {sources.length === 0 && !uploadingFile && <div className="empty-sources"><p>No documents yet.</p></div>}
            </div>
          </div>
        ) : (
          <div className="chat-container">
            <div className="chat-area premium-scroll">
              {messages.map((m, i) => (
                <div key={i} className={`message ${m.type === 'user' ? 'user-message' : 'ai-message'}`}>
                  <div className="msg-bubble">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                  </div>
                </div>
              ))}
              {loading && <div className="message ai-message"><div className="msg-bubble"><div className="typing-dots"><span></span><span></span><span></span></div></div></div>}
              <div ref={chatEndRef} />
            </div>
            <div className="input-container">
              <div className="input-pill">
                <input type="text" className="chat-input" placeholder="Ask anything..." value={input} onChange={(e) => setInput(e.target.value)} onKeyPress={(e) => e.key === 'Enter' && handleSend()} disabled={!activeChat} />
                <button className="send-btn" onClick={handleSend} disabled={!activeChat || loading}><svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default App