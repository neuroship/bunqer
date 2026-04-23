/**
 * API client for communicating with the backend
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Token storage key
const TOKEN_KEY = 'vibe_accountant_token'
const USERNAME_KEY = 'vibe_accountant_username'

// Auth state callbacks
let onUnauthorizedCallback = null

/**
 * Set callback for unauthorized responses (401)
 */
export function setOnUnauthorized(callback) {
  onUnauthorizedCallback = callback
}

/**
 * Get stored auth token
 */
export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

/**
 * Get stored username
 */
export function getUsername() {
  return localStorage.getItem(USERNAME_KEY)
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated() {
  return !!getToken()
}

/**
 * Store auth credentials
 */
function setAuth(token, username) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USERNAME_KEY, username)
}

/**
 * Clear auth credentials
 */
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USERNAME_KEY)
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`
  const token = getToken()

  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...(token && { 'Authorization': `Bearer ${token}` }),
      ...options.headers
    },
    ...options
  }

  if (config.body && typeof config.body === 'object') {
    config.body = JSON.stringify(config.body)
  }

  const response = await fetch(url, config)

  // Handle unauthorized responses
  if (response.status === 401) {
    clearAuth()
    if (onUnauthorizedCallback) {
      onUnauthorizedCallback()
    }
    throw new Error('Session expired. Please log in again.')
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || 'Request failed')
  }

  return response.json()
}

// Auth
export const auth = {
  login: async (username, password) => {
    const response = await request('/auth/login', {
      method: 'POST',
      body: { username, password }
    })
    // If MFA required, don't store token yet — caller handles MFA step
    if (!response.mfa_required) {
      setAuth(response.access_token, response.username)
    }
    return response
  },
  logout: () => {
    clearAuth()
  }
}

// Passkeys (WebAuthn)
function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function base64urlToBuffer(base64url) {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const pad = base64.length % 4 === 0 ? '' : '='.repeat(4 - (base64.length % 4))
  const binary = atob(base64 + pad)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

export const passkeys = {
  /** Check if WebAuthn is supported by this browser */
  isSupported: () => !!window.PublicKeyCredential,

  /** List registered passkeys (requires auth) */
  list: () => request('/auth/passkeys'),

  /** Delete a passkey (requires auth) */
  delete: (id) => request(`/auth/passkeys/${id}`, { method: 'DELETE' }),

  /** Register a new passkey (requires auth) */
  register: async (name) => {
    // 1. Get options from server
    const options = await request('/auth/passkeys/register-options')

    // 2. Convert to browser-friendly format
    const publicKey = {
      challenge: base64urlToBuffer(options.challenge),
      rp: options.rp,
      user: {
        id: base64urlToBuffer(options.user.id),
        name: options.user.name,
        displayName: options.user.displayName,
      },
      pubKeyCredParams: options.pubKeyCredParams,
      timeout: options.timeout,
      excludeCredentials: (options.excludeCredentials || []).map(c => ({
        type: c.type,
        id: base64urlToBuffer(c.id),
      })),
      authenticatorSelection: options.authenticatorSelection,
      attestation: options.attestation,
    }

    // 3. Create credential via browser API
    const credential = await navigator.credentials.create({ publicKey })

    // 4. Send to server for verification
    const result = await request('/auth/passkeys/register', {
      method: 'POST',
      body: {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        response: {
          attestationObject: bufferToBase64url(credential.response.attestationObject),
          clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        },
        name: name || 'Passkey',
      }
    })
    return result
  },

  /** Complete MFA step after password login (uses mfa_token) */
  verifyMfa: async (mfaToken) => {
    // 1. Get MFA challenge options from server
    const options = await request(`/auth/passkeys/mfa-options?mfa_token=${encodeURIComponent(mfaToken)}`)

    // 2. Convert to browser-friendly format
    const publicKey = {
      challenge: base64urlToBuffer(options.challenge),
      rpId: options.rpId,
      timeout: options.timeout,
      allowCredentials: (options.allowCredentials || []).map(c => ({
        type: c.type,
        id: base64urlToBuffer(c.id),
      })),
      userVerification: options.userVerification,
    }

    // 3. Get assertion via browser API
    const assertion = await navigator.credentials.get({ publicKey })

    // 4. Send assertion + mfa_token to server for verification
    const response = await request('/auth/passkeys/verify-mfa', {
      method: 'POST',
      body: {
        mfa_token: mfaToken,
        id: assertion.id,
        rawId: bufferToBase64url(assertion.rawId),
        type: assertion.type,
        response: {
          authenticatorData: bufferToBase64url(assertion.response.authenticatorData),
          clientDataJSON: bufferToBase64url(assertion.response.clientDataJSON),
          signature: bufferToBase64url(assertion.response.signature),
          userHandle: assertion.response.userHandle
            ? bufferToBase64url(assertion.response.userHandle)
            : null,
        },
      }
    })

    setAuth(response.access_token, response.username)
    return response
  },
}

// Health
export const health = {
  check: () => request('/health')
}

// Integrations
export const integrations = {
  list: () => request('/integrations'),
  get: (id) => request(`/integrations/${id}`),
  create: (data) => request('/integrations', { method: 'POST', body: data }),
  delete: (id) => request(`/integrations/${id}`, { method: 'DELETE' })
}

// Setup
export const setup = {
  startBunq: (data) => request('/setup/bunq/start', { method: 'POST', body: data }),
  setupAccounts: (data) => request('/setup/bunq/accounts', { method: 'POST', body: data }),
  syncNow: () => request('/setup/sync-now', { method: 'POST' }),
  resync: () => request('/setup/resync', { method: 'POST' })
}

// Transactions
export const transactions = {
  list: (params = {}) => {
    // Filter out empty values
    const filteredParams = Object.fromEntries(
      Object.entries(params).filter(([_, v]) => v !== '' && v !== null && v !== undefined)
    )
    const query = new URLSearchParams(filteredParams).toString()
    return request(`/transactions${query ? `?${query}` : ''}`)
  },
  get: (id) => request(`/transactions/${id}`),
  getRaw: (id) => request(`/transactions/${id}/raw`),
  update: (id, data) => request(`/transactions/${id}`, { method: 'PATCH', body: data }),
  filters: () => request('/transactions/filters'),
  stats: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/transactions/stats${query ? `?${query}` : ''}`)
  },
  applyRules: () => request('/transactions/apply-rules', { method: 'POST' }),
  matchDocuments: () => request('/transactions/match-documents', { method: 'POST' })
}

// Categories
export const categories = {
  list: () => request('/categories'),
  get: (id) => request(`/categories/${id}`),
  create: (data) => request('/categories', { method: 'POST', body: data }),
  update: (id, data) => request(`/categories/${id}`, { method: 'PATCH', body: data }),
  delete: (id) => request(`/categories/${id}`, { method: 'DELETE' }),
  export: () => request('/categories/export'),
  import: (data) => request('/categories/import', { method: 'POST', body: data }),
  // Rules
  rules: {
    list: (categoryId) => request(`/categories/${categoryId}/rules`),
    get: (ruleId) => request(`/categories/rules/${ruleId}`),
    create: (categoryId, data) => request(`/categories/${categoryId}/rules`, { method: 'POST', body: data }),
    update: (ruleId, data) => request(`/categories/rules/${ruleId}`, { method: 'PATCH', body: data }),
    delete: (ruleId) => request(`/categories/rules/${ruleId}`, { method: 'DELETE' })
  }
}

// Clients
export const clients = {
  list: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/invoices/clients${query ? `?${query}` : ''}`)
  },
  get: (id) => request(`/invoices/clients/${id}`),
  create: (data) => request('/invoices/clients', { method: 'POST', body: data }),
  update: (id, data) => request(`/invoices/clients/${id}`, { method: 'PUT', body: data }),
  delete: (id) => request(`/invoices/clients/${id}`, { method: 'DELETE' })
}

// Invoices
export const invoices = {
  list: (params = {}) => {
    const query = new URLSearchParams(params).toString()
    return request(`/invoices${query ? `?${query}` : ''}`)
  },
  get: (id) => request(`/invoices/${id}`),
  create: (data) => request('/invoices', { method: 'POST', body: data }),
  update: (id, data) => request(`/invoices/${id}`, { method: 'PUT', body: data }),
  delete: (id) => request(`/invoices/${id}`, { method: 'DELETE' }),
  send: (id) => request(`/invoices/${id}/send`, { method: 'POST' }),
  markPaid: (id) => request(`/invoices/${id}/mark-paid`, { method: 'POST' }),
  nextNumber: () => request('/invoices/next-number'),
  downloadPdf: async (id) => {
    const url = `${API_BASE}/invoices/${id}/pdf`
    const token = getToken()
    const response = await fetch(url, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    })
    if (response.status === 401) {
      clearAuth()
      if (onUnauthorizedCallback) onUnauthorizedCallback()
      throw new Error('Session expired. Please log in again.')
    }
    if (!response.ok) throw new Error('Failed to download PDF')
    const blob = await response.blob()
    const blobUrl = URL.createObjectURL(blob)
    // Extract filename from Content-Disposition header, fall back to invoice id
    let filename = `invoice-${id}.pdf`
    const disposition = response.headers.get('Content-Disposition')
    if (disposition) {
      const match = disposition.match(/filename="?([^";\n]+)"?/)
      if (match) filename = match[1]
    }
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(blobUrl)
  }
}

// Documents
export const documents = {
  list: (params = {}) => {
    const filteredParams = Object.fromEntries(
      Object.entries(params).filter(([_, v]) => v !== '' && v !== null && v !== undefined)
    )
    const query = new URLSearchParams(filteredParams).toString()
    return request(`/documents${query ? `?${query}` : ''}`)
  },
  get: (id) => request(`/documents/${id}`),
  upload: async (file, docType) => {
    const url = `${API_BASE}/documents?doc_type=${encodeURIComponent(docType)}`
    const token = getToken()
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(url, {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      body: formData
    })
    if (response.status === 401) {
      clearAuth()
      if (onUnauthorizedCallback) onUnauthorizedCallback()
      throw new Error('Session expired. Please log in again.')
    }
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(error.detail || 'Upload failed')
    }
    return response.json()
  },
  updateType: (id, docType, reprocess = false) => request(`/documents/${id}?doc_type=${encodeURIComponent(docType)}&reprocess=${reprocess}`, { method: 'PATCH' }),
  getViewUrl: (id) => request(`/documents/${id}/view-url`),
  reprocess: (id) => request(`/documents/${id}/reprocess`, { method: 'POST' }),
  delete: (id) => request(`/documents/${id}`, { method: 'DELETE' }),
  findDuplicates: () => request('/documents/duplicates/find'),
  deleteDuplicate: (docId, keepId) => request(`/documents/duplicates/${docId}?keep_id=${keepId}`, { method: 'DELETE' }),
  backfillHashes: () => request('/documents/duplicates/backfill-hashes', { method: 'POST' }),
}

// Company Settings
export const companySettings = {
  get: () => request('/settings/company'),
  update: (data) => request('/settings/company', { method: 'PUT', body: data }),
  uploadLogo: async (file) => {
    const url = `${API_BASE}/settings/company/logo`
    const token = getToken()
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(url, {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      body: formData
    })
    if (response.status === 401) {
      clearAuth()
      if (onUnauthorizedCallback) onUnauthorizedCallback()
      throw new Error('Session expired. Please log in again.')
    }
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(error.detail || 'Upload failed')
    }
    return response.json()
  },
  deleteLogo: () => request('/settings/company/logo', { method: 'DELETE' })
}

// Events (SSE)
export function subscribeToEvents(onEvent) {
  const token = getToken()
  if (!token) {
    console.warn('Cannot subscribe to events: not authenticated')
    return () => {}
  }

  const controller = new AbortController()

  async function connect() {
    try {
      const response = await fetch(`${API_BASE}/events/stream`, {
        headers: { 'Authorization': `Bearer ${token}` },
        signal: controller.signal,
      })

      if (!response.ok) {
        if (response.status === 401 && onUnauthorizedCallback) {
          onUnauthorizedCallback()
        }
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop()

        for (const chunk of chunks) {
          const dataLine = chunk.split('\n').find(l => l.startsWith('data: '))
          if (dataLine) {
            try {
              const data = JSON.parse(dataLine.slice(6))
              onEvent(data)
            } catch (e) {
              console.error('Failed to parse event:', e)
            }
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        console.error('SSE connection error:', e)
      }
    }
  }

  connect()

  return () => controller.abort()
}

export default {
  auth,
  health,
  integrations,
  setup,
  transactions,
  categories,
  clients,
  invoices,
  documents,
  companySettings,
  passkeys,
  subscribeToEvents,
  isAuthenticated,
  getUsername,
  clearAuth,
  setOnUnauthorized
}
