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
  let runDocs = $state([])
  let runDocsLoading = $state(false)

  // Gmail preview modal
  let previewTarget = $state(null)
  let previewData = $state(null)
  let previewLoading = $state(false)

  // Run quarter modal (runTarget = a source, or 'all')
  let runTarget = $state(null)
  let runYear = $state(new Date().getFullYear())
  let runQuarter = $state(Math.floor(new Date().getMonth() / 3) + 1)
  let starting = $state(false)

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
      gmail_query: '',
      collect_description: ''
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
    if (gmail === 'error') window.showToast?.(`Gmail connection failed: ${params.get('reason') || 'unknown error'}`, 'error')
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
      gmail_query: src.gmail_query || '',
      collect_description: src.collect_description || ''
    }
    showModal = true
  }

  async function saveSource() {
    if (!form.name.trim()) {
      window.showToast?.('Name is required', 'error')
      return
    }
    if (form.kind === 'gmail' && !form.collect_description.trim() && !form.gmail_query.trim()) {
      window.showToast?.('Describe what to collect', 'error')
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
        gmail_query: form.gmail_query.trim() || null,
        collect_description: form.collect_description.trim() || null
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

  function quarterRange(year, q) {
    const from = `${year}-${String((q - 1) * 3 + 1).padStart(2, '0')}-01`
    const endMonth = q * 3
    const lastDay = new Date(year, endMonth, 0).getDate()
    const to = `${year}-${String(endMonth).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
    return { date_from: from, date_to: to }
  }

  function quarterLabel(run) {
    if (!run.date_from || !run.date_to) return `${run.date_from || '…'} → ${run.date_to || '…'}`
    const [y, m, d] = run.date_from.split('-').map(Number)
    const q = Math.floor((m - 1) / 3) + 1
    const r = quarterRange(y, q)
    return r.date_from === run.date_from && r.date_to === run.date_to ? `Q${q} ${y}` : `${run.date_from} → ${run.date_to}`
  }

  const yearOptions = Array.from({ length: 4 }, (_, i) => new Date().getFullYear() - i)

  function openRun(target) {
    const now = new Date()
    runYear = now.getFullYear()
    runQuarter = Math.floor(now.getMonth() / 3) + 1
    runTarget = target
  }

  async function runNow() {
    if (!runTarget) return
    const period = quarterRange(runYear, runQuarter)
    starting = true
    try {
      const res = runTarget === 'all'
        ? await api.invoiceSources.runAll(period)
        : await api.invoiceSources.run(runTarget.id, period)
      window.showToast?.(res.detail, 'info')
      runningIds = runTarget === 'all' ? new Set(sources.map(s => s.id)) : new Set([...runningIds, runTarget.id])
      runTarget = null
      if (!pollInterval) pollInterval = setInterval(loadAll, 5000)
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      starting = false
    }
  }

  function openPreview(src) {
    const now = new Date()
    runYear = now.getFullYear()
    runQuarter = Math.floor(now.getMonth() / 3) + 1
    previewData = null
    previewTarget = src
  }

  async function loadPreview() {
    if (!previewTarget) return
    previewLoading = true
    previewData = null
    try {
      previewData = await api.invoiceSources.gmailPreview(previewTarget.id, quarterRange(runYear, runQuarter))
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      previewLoading = false
    }
  }

  async function runFromPreview() {
    const src = previewTarget
    previewTarget = null
    runTarget = src
    await runNow()
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

  async function openRunDetail(run) {
    selectedRun = run
    runDocs = []
    runDocsLoading = true
    try {
      runDocs = await api.invoiceSources.runDocuments(run.id)
    } catch (error) {
      console.error('Failed to load run documents:', error)
    } finally {
      runDocsLoading = false
    }
  }

  async function openDocument(doc) {
    try {
      const { url } = await api.documents.getViewUrl(doc.id)
      window.open(url, '_blank', 'noopener')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  function showInDocuments(doc) {
    window.dispatchEvent(new CustomEvent('navigate-to-document', { detail: { documentId: doc.id } }))
  }

  async function deleteRun(run) {
    try {
      await api.invoiceSources.deleteRun(run.id)
      if (selectedRun?.id === run.id) selectedRun = null
      await loadAll()
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function cleanupRuns() {
    if (!confirm('Delete all failed runs and runs that stored no documents?')) return
    try {
      const res = await api.invoiceSources.cleanupRuns()
      window.showToast?.(`Deleted ${res.deleted} run(s)`, 'success')
      await loadAll()
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  function fmtAmount(v) {
    return v == null ? '' : new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' }).format(v)
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
      <p class="text-xs text-va-muted mt-0.5">Collect purchase invoices from vendor portals and Gmail per quarter, then match them to transactions.</p>
    </div>
    <div class="flex items-center gap-2">
      {#if sources.length > 0}
        <Button variant="success" onclick={() => openRun('all')} disabled={runningIds.size > 0}>
          <span class="icon-[tabler--player-play] w-4 h-4"></span> Collect quarter
        </Button>
      {/if}
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
        <Card>
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <div class="w-8 h-8 rounded-lg bg-va-accent/15 flex items-center justify-center flex-shrink-0">
                <span class="{src.kind === 'gmail' ? 'icon-[tabler--mail]' : 'icon-[tabler--world]'} w-4 h-4 text-va-accent"></span>
              </div>
              <div class="min-w-0">
                <p class="text-sm font-medium text-va-text truncate">{src.name}</p>
                <p class="text-xs text-va-muted truncate">
                  {#if src.kind === 'gmail'}
                    {src.gmail_connected ? src.gmail_email : 'Not connected'}{src.collect_description ? ` · ${src.collect_description}` : ''}
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
                <button onclick={() => openPreview(src)} class="p-1.5 rounded-md text-va-muted hover:text-va-accent hover:bg-va-hover" title="Preview what a quarter would collect">
                  <span class="icon-[tabler--eye-search] w-4 h-4"></span>
                </button>
                <button onclick={() => disconnectGmail(src)} class="p-1.5 rounded-md text-va-muted hover:text-va-danger hover:bg-va-hover" title="Disconnect Gmail">
                  <span class="icon-[tabler--plug-connected-x] w-4 h-4"></span>
                </button>
              {/if}
              <button
                onclick={() => openRun(src)}
                disabled={runningIds.has(src.id) || (src.kind === 'gmail' && !src.gmail_connected)}
                class="p-1.5 rounded-md text-va-muted hover:text-va-success hover:bg-va-hover disabled:opacity-40"
                title="Collect a quarter from this source"
              >
                <span class="icon-[tabler--player-play] w-4 h-4"></span>
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

    <Card>
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-base font-semibold text-va-text">Recent runs</h2>
        {#if runs.some(r => r.status === 'failed' || (r.status !== 'running' && r.documents_new === 0))}
          <button onclick={cleanupRuns} class="text-xs text-va-muted hover:text-va-danger flex items-center gap-1" title="Delete failed runs and runs without documents">
            <span class="icon-[tabler--trash] w-3.5 h-3.5"></span> Clear failed & empty
          </button>
        {/if}
      </div>
      {#if runs.length === 0}
        <p class="text-xs text-va-muted">No runs yet.</p>
      {:else}
        <div class="overflow-x-auto">
          <table class="table table-sm w-full">
            <thead>
              <tr class="text-xs text-va-muted">
                <th>Source</th>
                <th>Started</th>
                <th>Period</th>
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
                <tr class="text-sm hover:bg-va-hover cursor-pointer" onclick={() => openRunDetail(run)}>
                  <td class="text-va-text">{run.source_name || run.source_id}</td>
                  <td class="text-va-muted text-xs">{fmtDate(run.started_at)}</td>
                  <td class="text-va-muted text-xs whitespace-nowrap">{quarterLabel(run)}</td>
                  <td class="text-va-muted text-xs">{duration(run)}</td>
                  <td><span class="badge badge-sm {statusColors[run.status] || ''}">{run.status}</span></td>
                  <td class="text-right">{run.documents_found}</td>
                  <td class="text-right {run.documents_new > 0 ? 'text-va-success' : ''}">{run.documents_new}</td>
                  <td class="text-right {run.documents_matched > 0 ? 'text-va-success' : ''}">{run.documents_matched}</td>
                  <td class="text-right whitespace-nowrap">
                    {#if run.status !== 'running'}
                      <button
                        onclick={(e) => { e.stopPropagation(); deleteRun(run) }}
                        class="text-va-muted hover:text-va-danger mr-1"
                        title="Delete run"
                      >
                        <span class="icon-[tabler--trash] w-4 h-4"></span>
                      </button>
                    {/if}
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
    <Input type="textarea" label="What to collect" bind:value={form.collect_description} placeholder="Tesla charging invoices, the monthly Hetzner invoice, Bol.com receipts" required />
    <p class="text-xs text-va-muted -mt-2 mb-3">Plain language. The AI writes the Gmail search for the chosen quarter, picks the emails that are real invoices, takes PDF attachments and turns attachment-less invoice emails into PDFs. Use Preview on the card to check before collecting.</p>
    <Input label="Advanced: fixed Gmail query (optional)" bind:value={form.gmail_query} placeholder="from:tesla.com subject:(invoice OR factuur)" />
    <p class="text-xs text-va-muted -mt-2 mb-3">Overrides the generated search; the quarter dates are still added.</p>
    {#if !editing}
      <p class="text-xs text-va-muted mb-3">After saving you will be redirected to Google to grant read-only access.</p>
    {/if}
  {/if}

  <div class="mb-2"></div>
  <div class="flex justify-end gap-2">
    <Button variant="secondary" onclick={() => showModal = false}>Cancel</Button>
    <Button onclick={saveSource} loading={saving}>{editing ? 'Save' : (form.kind === 'gmail' ? 'Save & connect' : 'Add')}</Button>
  </div>
</Modal>

<!-- Run quarter modal -->
<Modal show={!!runTarget} title={runTarget === 'all' ? 'Collect quarter from all sources' : `Collect quarter from ${runTarget?.name || ''}`} size="sm" onClose={() => runTarget = null}>
  {#if runTarget}
    <p class="text-xs text-va-muted mb-3">All invoices dated in the chosen quarter are collected{runTarget === 'all' ? ', one source after another' : ''}.</p>
    <div class="grid grid-cols-2 gap-3 mb-3">
      <div>
        <label class="block text-sm text-va-muted mb-1.5" for="run-quarter">Quarter</label>
        <select id="run-quarter" bind:value={runQuarter} class="select select-sm bg-va-canvas border-va-border text-va-text w-full">
          {#each [1, 2, 3, 4] as q}
            <option value={q}>Q{q}</option>
          {/each}
        </select>
      </div>
      <div>
        <label class="block text-sm text-va-muted mb-1.5" for="run-year">Year</label>
        <select id="run-year" bind:value={runYear} class="select select-sm bg-va-canvas border-va-border text-va-text w-full">
          {#each yearOptions as y}
            <option value={y}>{y}</option>
          {/each}
        </select>
      </div>
    </div>
    <p class="text-xs text-va-muted mb-4">{quarterRange(runYear, runQuarter).date_from} → {quarterRange(runYear, runQuarter).date_to}</p>
    <div class="flex justify-end gap-2">
      <Button variant="secondary" onclick={() => runTarget = null}>Cancel</Button>
      <Button onclick={runNow} loading={starting}>
        <span class="icon-[tabler--player-play] w-4 h-4"></span> Collect
      </Button>
    </div>
  {/if}
</Modal>

<!-- Gmail preview modal -->
<Modal show={!!previewTarget} title="Preview: {previewTarget?.name || ''}" size="2xl" onClose={() => previewTarget = null}>
  {#if previewTarget}
    <p class="text-xs text-va-muted mb-3">"{previewTarget.collect_description || previewTarget.gmail_query}"</p>
    <div class="flex items-end gap-3 mb-3">
      <div>
        <label class="block text-sm text-va-muted mb-1.5" for="pv-quarter">Quarter</label>
        <select id="pv-quarter" bind:value={runQuarter} class="select select-sm bg-va-canvas border-va-border text-va-text">
          {#each [1, 2, 3, 4] as q}<option value={q}>Q{q}</option>{/each}
        </select>
      </div>
      <div>
        <label class="block text-sm text-va-muted mb-1.5" for="pv-year">Year</label>
        <select id="pv-year" bind:value={runYear} class="select select-sm bg-va-canvas border-va-border text-va-text">
          {#each yearOptions as y}<option value={y}>{y}</option>{/each}
        </select>
      </div>
      <Button variant="secondary" onclick={loadPreview} loading={previewLoading}>
        <span class="icon-[tabler--search] w-4 h-4"></span> Search
      </Button>
    </div>
    {#if previewData}
      <p class="text-xs text-va-muted mb-1">Gmail query</p>
      <code class="block text-xs text-va-accent bg-va-canvas border border-va-border rounded px-2 py-1.5 mb-3 break-all">{previewData.query}</code>
      {#if previewData.messages.length === 0}
        <p class="text-xs text-va-muted mb-3">No emails matched in this quarter. Refine the description or use a fixed query.</p>
      {:else}
        <p class="text-xs text-va-muted mb-2">{previewData.messages.filter(m => m.selected).length} of {previewData.messages.length} matched emails judged to be invoices. Checked rows would be collected.</p>
        <div class="space-y-1 max-h-72 overflow-y-auto mb-3">
          {#each previewData.messages as m (m.id)}
            <div class="flex items-start gap-2 p-2 rounded-lg border {m.selected ? 'border-va-success/40 bg-va-success/5' : 'border-va-border opacity-60'}">
              <span class="{m.selected ? 'icon-[tabler--check]' : 'icon-[tabler--x]'} w-4 h-4 mt-0.5 flex-shrink-0 {m.selected ? 'text-va-success' : 'text-va-muted'}"></span>
              <div class="min-w-0 flex-1">
                <p class="text-sm text-va-text truncate">{m.subject}</p>
                <p class="text-xs text-va-muted truncate">{m.from} · {m.date}</p>
              </div>
              <span class="badge badge-xs {m.pdf_count > 0 ? 'badge-info' : ''} flex-shrink-0" title={m.pdf_count > 0 ? 'PDF attachment' : 'No attachment: email body becomes the PDF'}>
                {m.pdf_count > 0 ? `${m.pdf_count} PDF` : 'body'}
              </span>
            </div>
          {/each}
        </div>
      {/if}
      <div class="flex justify-end gap-2">
        <Button variant="secondary" onclick={() => previewTarget = null}>Close</Button>
        <Button onclick={runFromPreview} disabled={!previewData.messages.some(m => m.selected)}>
          <span class="icon-[tabler--player-play] w-4 h-4"></span> Collect Q{runQuarter} {runYear}
        </Button>
      </div>
    {/if}
  {/if}
</Modal>

<!-- Run detail modal -->
<Modal show={!!selectedRun} title="Run details" size="2xl" onClose={() => selectedRun = null}>
  {#if selectedRun}
    <div class="flex items-center gap-3 text-xs text-va-muted mb-3">
      <span class="badge badge-sm {statusColors[selectedRun.status] || ''}">{selectedRun.status}</span>
      <span>{selectedRun.source_name}</span>
      <span>{fmtDate(selectedRun.started_at)}</span>
      <span>{quarterLabel(selectedRun)}</span>
      <span>{duration(selectedRun)}</span>
      {#if selectedRun.browserbase_session_id}
        <a href="https://browserbase.com/sessions/{selectedRun.browserbase_session_id}" target="_blank" rel="noopener" class="text-va-accent hover:underline">Session replay</a>
      {/if}
    </div>
    {#if selectedRun.error}
      <div class="text-xs text-va-danger bg-va-danger/10 border border-va-danger/30 rounded-lg p-3 mb-3 whitespace-pre-wrap">{selectedRun.error}</div>
    {/if}

    <h4 class="text-sm font-medium text-va-text mb-2">Fetched invoices</h4>
    {#if runDocsLoading}
      <div class="flex items-center gap-2 text-xs text-va-muted mb-3">
        <div class="w-4 h-4 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div> Loading…
      </div>
    {:else if runDocs.length === 0}
      <p class="text-xs text-va-muted mb-3">No documents were stored by this run.</p>
    {:else}
      <div class="space-y-1.5 mb-4">
        {#each runDocs as doc (doc.id)}
          <div class="flex items-center justify-between gap-3 p-2.5 bg-va-canvas rounded-lg border border-va-border">
            <div class="flex items-center gap-3 min-w-0">
              <span class="icon-[tabler--file-type-pdf] w-5 h-5 text-va-danger flex-shrink-0"></span>
              <div class="min-w-0">
                <p class="text-sm text-va-text truncate">{doc.vendor_name || doc.filename}</p>
                <p class="text-xs text-va-muted truncate">
                  {doc.invoice_number ? `#${doc.invoice_number} · ` : ''}{doc.invoice_date || ''}{doc.total_amount != null ? ` · ${fmtAmount(doc.total_amount)}` : ''}
                  {#if doc.status !== 'completed'}<span class="badge badge-xs {statusColors[doc.status] || ''} ml-1">{doc.status}</span>{/if}
                  {#if doc.matched_transactions?.length}<span class="badge badge-xs badge-success ml-1">matched</span>{/if}
                </p>
              </div>
            </div>
            <div class="flex items-center gap-1 flex-shrink-0">
              <button onclick={() => openDocument(doc)} class="p-1.5 rounded-md text-va-muted hover:text-va-accent hover:bg-va-hover" title="Open / download PDF">
                <span class="icon-[tabler--download] w-4 h-4"></span>
              </button>
              <button onclick={() => showInDocuments(doc)} class="p-1.5 rounded-md text-va-muted hover:text-va-text hover:bg-va-hover" title="Show in Documents">
                <span class="icon-[tabler--external-link] w-4 h-4"></span>
              </button>
            </div>
          </div>
        {/each}
      </div>
    {/if}
    <pre class="text-xs text-va-muted bg-va-canvas border border-va-border rounded-lg p-3 overflow-x-auto max-h-96 whitespace-pre-wrap">{selectedRun.log || 'No log output.'}</pre>
  {/if}
</Modal>
