<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Button from '../components/Button.svelte'
  import Modal from '../components/Modal.svelte'
  import Input from '../components/Input.svelte'
  import api from '../api.js'

  let sources = $state([])
  let runs = $state([])
  let loading = $state(true)
  let runningIds = $state(new Set())

  // Create / edit modal
  let showModal = $state(false)
  let editing = $state(null)
  let saving = $state(false)
  let form = $state(blankForm())

  // Run detail modal
  let selectedRun = $state(null)

  let pollInterval = null

  const statusColors = {
    running: 'badge-info',
    completed: 'badge-success',
    failed: 'badge-error'
  }

  function blankForm() {
    return {
      name: '',
      kind: 'website',
      enabled: true,
      login_url: '',
      op_username_ref: '',
      op_password_ref: '',
      op_totp_ref: '',
      instructions: '',
      gmail_query: ''
    }
  }

  async function loadAll() {
    try {
      const [s, r] = await Promise.all([api.invoiceSources.list(), api.invoiceSources.runs({ limit: 30 })])
      sources = s
      runs = r
      const active = new Set(s.filter(x => x.last_status === 'running').map(x => x.id))
      runningIds = active
      if (active.size > 0 && !pollInterval) {
        pollInterval = setInterval(loadAll, 5000)
      } else if (active.size === 0 && pollInterval) {
        clearInterval(pollInterval)
        pollInterval = null
      }
    } catch (error) {
      console.error('Failed to load sources:', error)
    } finally {
      loading = false
    }
  }

  onMount(() => {
    loadAll()
    const params = new URLSearchParams(window.location.hash.split('?')[1] || '')
    const gmail = params.get('gmail')
    if (gmail === 'connected') window.showToast?.('Gmail connected', 'success')
    if (gmail === 'error') window.showToast?.('Gmail connection failed', 'error')
    if (gmail) window.location.hash = 'fetchers'

    const onUpdate = () => loadAll()
    window.addEventListener('fetch-updated', onUpdate)
    return () => {
      window.removeEventListener('fetch-updated', onUpdate)
      if (pollInterval) clearInterval(pollInterval)
    }
  })

  function openCreate(kind = 'website') {
    editing = null
    form = { ...blankForm(), kind }
    showModal = true
  }

  function openEdit(src) {
    editing = src
    form = {
      name: src.name,
      kind: src.kind,
      enabled: src.enabled,
      login_url: src.login_url || '',
      op_username_ref: src.op_username_ref || '',
      op_password_ref: src.op_password_ref || '',
      op_totp_ref: src.op_totp_ref || '',
      instructions: src.instructions || '',
      gmail_query: src.gmail_query || ''
    }
    showModal = true
  }

  async function saveSource() {
    if (!form.name.trim()) {
      window.showToast?.('Name is required', 'error')
      return
    }
    if (form.kind === 'website' && (!form.login_url.trim() || !form.op_username_ref.trim() || !form.op_password_ref.trim())) {
      window.showToast?.('Login URL and both 1Password references are required', 'error')
      return
    }
    saving = true
    try {
      const body = {
        name: form.name.trim(),
        enabled: form.enabled,
        login_url: form.login_url.trim() || null,
        op_username_ref: form.op_username_ref.trim() || null,
        op_password_ref: form.op_password_ref.trim() || null,
        op_totp_ref: form.op_totp_ref.trim() || null,
        instructions: form.instructions.trim() || null,
        gmail_query: form.gmail_query.trim() || null
      }
      let saved
      if (editing) {
        saved = await api.invoiceSources.update(editing.id, body)
      } else {
        saved = await api.invoiceSources.create({ ...body, kind: form.kind })
      }
      showModal = false
      await loadAll()
      if (!editing && saved.kind === 'gmail') await connectGmail(saved)
      window.showToast?.(editing ? 'Source updated' : 'Source added', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      saving = false
    }
  }

  async function deleteSource(src) {
    if (!confirm(`Delete "${src.name}"? Fetched documents stay.`)) return
    try {
      await api.invoiceSources.delete(src.id)
      await loadAll()
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function toggleEnabled(src) {
    try {
      await api.invoiceSources.update(src.id, { enabled: !src.enabled })
      await loadAll()
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function runNow(src) {
    try {
      const res = await api.invoiceSources.run(src.id)
      window.showToast?.(res.detail, 'info')
      runningIds = new Set([...runningIds, src.id])
      if (!pollInterval) pollInterval = setInterval(loadAll, 5000)
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function connectGmail(src) {
    try {
      const { url } = await api.invoiceSources.gmailAuthUrl(src.id)
      window.location.href = url
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function disconnectGmail(src) {
    try {
      await api.invoiceSources.gmailDisconnect(src.id)
      await loadAll()
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  function fmtDate(d) {
    return d ? new Date(d).toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' }) : '—'
  }

  function duration(run) {
    if (!run.finished_at) return '…'
    const s = Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000)
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
  }
</script>

<div class="max-w-6xl">
  <div class="flex items-center justify-between mb-4">
    <div>
      <h2 class="text-lg font-semibold text-va-text">Auto-Fetch</h2>
      <p class="text-xs text-va-muted mt-0.5">Collect purchase invoices from vendor portals and Gmail, then match them to transactions. Runs daily.</p>
    </div>
    <div class="flex items-center gap-2">
      <Button variant="secondary" onclick={() => openCreate('gmail')}>
        <span class="icon-[tabler--mail] w-4 h-4"></span> Gmail
      </Button>
      <Button onclick={() => openCreate('website')}>
        <span class="icon-[tabler--world] w-4 h-4"></span> Website
      </Button>
    </div>
  </div>

  {#if loading}
    <div class="flex items-center justify-center h-32">
      <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if sources.length === 0}
    <Card>
      <div class="flex flex-col items-center py-8 text-center">
        <span class="icon-[tabler--robot] w-10 h-10 text-va-muted mb-3"></span>
        <p class="text-sm text-va-text">No sources yet</p>
        <p class="text-xs text-va-muted mt-1 max-w-md">
          Add a vendor website (login via 1Password + Browserbase) or connect Gmail. Configure provider keys under Settings first.
        </p>
      </div>
    </Card>
  {:else}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
      {#each sources as src (src.id)}
        <Card class={src.enabled ? '' : 'opacity-60'}>
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <div class="w-8 h-8 rounded-lg bg-va-accent/15 flex items-center justify-center flex-shrink-0">
                <span class="{src.kind === 'gmail' ? 'icon-[tabler--mail]' : 'icon-[tabler--world]'} w-4 h-4 text-va-accent"></span>
              </div>
              <div class="min-w-0">
                <p class="text-sm font-medium text-va-text truncate">{src.name}</p>
                <p class="text-xs text-va-muted truncate">
                  {#if src.kind === 'gmail'}
                    {src.gmail_connected ? src.gmail_email : 'Not connected'}
                  {:else}
                    {src.login_url}
                  {/if}
                </p>
                <div class="flex items-center gap-2 mt-2 text-xs text-va-muted">
                  {#if runningIds.has(src.id)}
                    <span class="badge badge-sm badge-info">running</span>
                  {:else if src.last_status}
                    <span class="badge badge-sm {statusColors[src.last_status] || ''}">{src.last_status}</span>
                  {:else}
                    <span class="badge badge-sm">never run</span>
                  {/if}
                  <span>{fmtDate(src.last_run_at)}</span>
                </div>
              </div>
            </div>
            <div class="flex items-center gap-1 flex-shrink-0">
              {#if src.kind === 'gmail' && !src.gmail_connected}
                <button onclick={() => connectGmail(src)} class="p-1.5 rounded-md text-va-accent hover:bg-va-hover" title="Connect Gmail">
                  <span class="icon-[tabler--plug-connected] w-4 h-4"></span>
                </button>
              {:else if src.kind === 'gmail'}
                <button onclick={() => disconnectGmail(src)} class="p-1.5 rounded-md text-va-muted hover:text-va-danger hover:bg-va-hover" title="Disconnect Gmail">
                  <span class="icon-[tabler--plug-connected-x] w-4 h-4"></span>
                </button>
              {/if}
              <button
                onclick={() => runNow(src)}
                disabled={runningIds.has(src.id) || (src.kind === 'gmail' && !src.gmail_connected)}
                class="p-1.5 rounded-md text-va-muted hover:text-va-success hover:bg-va-hover disabled:opacity-40"
                title="Run now"
              >
                <span class="icon-[tabler--player-play] w-4 h-4"></span>
              </button>
              <button onclick={() => toggleEnabled(src)} class="p-1.5 rounded-md text-va-muted hover:text-va-text hover:bg-va-hover" title={src.enabled ? 'Disable' : 'Enable'}>
                <span class="{src.enabled ? 'icon-[tabler--toggle-right]' : 'icon-[tabler--toggle-left]'} w-4 h-4"></span>
              </button>
              <button onclick={() => openEdit(src)} class="p-1.5 rounded-md text-va-muted hover:text-va-text hover:bg-va-hover" title="Edit">
                <span class="icon-[tabler--pencil] w-4 h-4"></span>
              </button>
              <button onclick={() => deleteSource(src)} class="p-1.5 rounded-md text-va-muted hover:text-va-danger hover:bg-va-hover" title="Delete">
                <span class="icon-[tabler--trash] w-4 h-4"></span>
              </button>
            </div>
          </div>
        </Card>
      {/each}
    </div>

    <Card title="Recent runs">
      {#if runs.length === 0}
        <p class="text-xs text-va-muted">No runs yet.</p>
      {:else}
        <div class="overflow-x-auto">
          <table class="table table-sm w-full">
            <thead>
              <tr class="text-xs text-va-muted">
                <th>Source</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Status</th>
                <th class="text-right">Found</th>
                <th class="text-right">New</th>
                <th class="text-right">Matched</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {#each runs as run (run.id)}
                <tr class="text-sm hover:bg-va-hover cursor-pointer" onclick={() => selectedRun = run}>
                  <td class="text-va-text">{run.source_name || run.source_id}</td>
                  <td class="text-va-muted text-xs">{fmtDate(run.started_at)}</td>
                  <td class="text-va-muted text-xs">{duration(run)}</td>
                  <td><span class="badge badge-sm {statusColors[run.status] || ''}">{run.status}</span></td>
                  <td class="text-right">{run.documents_found}</td>
                  <td class="text-right {run.documents_new > 0 ? 'text-va-success' : ''}">{run.documents_new}</td>
                  <td class="text-right {run.documents_matched > 0 ? 'text-va-success' : ''}">{run.documents_matched}</td>
                  <td class="text-right">
                    {#if run.browserbase_session_id}
                      <a
                        href="https://browserbase.com/sessions/{run.browserbase_session_id}"
                        target="_blank"
                        rel="noopener"
                        class="text-va-accent hover:underline text-xs"
                        onclick={(e) => e.stopPropagation()}
                        title="Open session replay"
                      >
                        <span class="icon-[tabler--video] w-4 h-4"></span>
                      </a>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </Card>
  {/if}
</div>

<!-- Create / edit modal -->
<Modal bind:show={showModal} title={editing ? 'Edit source' : (form.kind === 'gmail' ? 'Add Gmail source' : 'Add website source')} size="lg">
  <Input label="Name" bind:value={form.name} placeholder={form.kind === 'gmail' ? 'Work Gmail' : 'Hetzner Cloud'} required />

  {#if form.kind === 'website'}
    <Input label="Login URL" bind:value={form.login_url} placeholder="https://console.vendor.com/login" required />
    <Input label="1Password username reference" bind:value={form.op_username_ref} placeholder="op://Private/MijnKPN/email" required />
    <Input label="1Password password reference" bind:value={form.op_password_ref} placeholder="op://Private/MijnKPN/password" required />
    <Input label="1Password one-time password reference (optional, for 2FA)" bind:value={form.op_totp_ref} placeholder="op://bunqer/MijnKPN/one-time password" />
    <p class="text-xs text-va-muted -mt-2 mb-3">Same format as <code>op read</code>: <code>op://Vault/Item/field</code>. Field is the label in the item (often <code>username</code> or <code>email</code>). Resolved via the Service Account, never shown to the AI. A fresh 2FA code is fetched right after the login submit.</p>
    <Input type="textarea" label="Navigation hint (optional)" bind:value={form.instructions} placeholder="Billing > Invoices, then open each PDF" />
  {:else}
    <Input label="Gmail search query" bind:value={form.gmail_query} placeholder="has:attachment filename:pdf (invoice OR factuur) newer_than:90d" />
    <p class="text-xs text-va-muted -mt-2 mb-3">Leave empty for the default query. Only PDF attachments are collected.</p>
    {#if !editing}
      <p class="text-xs text-va-muted mb-3">After saving you will be redirected to Google to grant read-only access.</p>
    {/if}
  {/if}

  <label class="flex items-center gap-2 text-sm text-va-muted mb-4">
    <input type="checkbox" bind:checked={form.enabled} class="checkbox checkbox-sm" />
    Enabled (included in the daily run)
  </label>

  <div class="flex justify-end gap-2">
    <Button variant="secondary" onclick={() => showModal = false}>Cancel</Button>
    <Button onclick={saveSource} loading={saving}>{editing ? 'Save' : (form.kind === 'gmail' ? 'Save & connect' : 'Add')}</Button>
  </div>
</Modal>

<!-- Run detail modal -->
<Modal show={!!selectedRun} title="Run details" size="2xl" onClose={() => selectedRun = null}>
  {#if selectedRun}
    <div class="flex items-center gap-3 text-xs text-va-muted mb-3">
      <span class="badge badge-sm {statusColors[selectedRun.status] || ''}">{selectedRun.status}</span>
      <span>{selectedRun.source_name}</span>
      <span>{fmtDate(selectedRun.started_at)}</span>
      <span>{duration(selectedRun)}</span>
      {#if selectedRun.browserbase_session_id}
        <a href="https://browserbase.com/sessions/{selectedRun.browserbase_session_id}" target="_blank" rel="noopener" class="text-va-accent hover:underline">Session replay</a>
      {/if}
    </div>
    {#if selectedRun.error}
      <div class="text-xs text-va-danger bg-va-danger/10 border border-va-danger/30 rounded-lg p-3 mb-3 whitespace-pre-wrap">{selectedRun.error}</div>
    {/if}
    <pre class="text-xs text-va-muted bg-va-canvas border border-va-border rounded-lg p-3 overflow-x-auto max-h-96 whitespace-pre-wrap">{selectedRun.log || 'No log output.'}</pre>
  {/if}
</Modal>
