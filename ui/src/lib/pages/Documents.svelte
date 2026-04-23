<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Button from '../components/Button.svelte'
  import Modal from '../components/Modal.svelte'
  import api from '../api.js'

  let documents = $state([])
  let total = $state(0)
  let loading = $state(true)
  let uploading = $state(false)

  // Filters
  let filterType = $state('')
  let filterStatus = $state('')
  let filterSearch = $state('')
  let filterVendor = $state('')
  let filterDateFrom = $state('')
  let filterDateTo = $state('')

  // Upload
  let showUploadModal = $state(false)
  let uploadFiles = $state([])
  let uploadDocType = $state('purchase_invoice')

  // Detail
  let showDetailModal = $state(false)
  let selectedDoc = $state(null)
  let detailLoading = $state(false)

  // Polling for processing docs
  let pollInterval = null

  const docTypeLabels = {
    sales_invoice: 'Sales Invoice',
    purchase_invoice: 'Purchase Invoice',
    tax_letter: 'Tax Letter'
  }

  const statusColors = {
    pending: 'badge-warning',
    processing: 'badge-info',
    completed: 'badge-success',
    failed: 'badge-error'
  }

  let debounceTimer = null

  // Single reactive effect for all filters
  $effect(() => {
    // Track all filter values
    filterType; filterStatus; filterSearch; filterVendor; filterDateFrom; filterDateTo;
    // Debounce to batch rapid changes
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => loadDocuments(), 200)
  })

  onMount(() => {
    return () => {
      if (pollInterval) clearInterval(pollInterval)
      clearTimeout(debounceTimer)
    }
  })

  async function loadDocuments() {
    loading = true
    try {
      const params = {}
      if (filterType) params.doc_type = filterType
      if (filterStatus) params.status = filterStatus
      if (filterSearch) params.search = filterSearch
      if (filterVendor) params.vendor = filterVendor
      if (filterDateFrom) params.date_from = filterDateFrom
      if (filterDateTo) params.date_to = filterDateTo

      const res = await api.documents.list(params)
      documents = res.documents
      total = res.total

      // Poll if any doc is processing
      const hasProcessing = documents.some(d => d.status === 'pending' || d.status === 'processing')
      if (hasProcessing && !pollInterval) {
        pollInterval = setInterval(loadDocuments, 4000)
      } else if (!hasProcessing && pollInterval) {
        clearInterval(pollInterval)
        pollInterval = null
      }
    } catch (error) {
      console.error('Failed to load documents:', error)
    } finally {
      loading = false
    }
  }

  function handleFileSelect(e) {
    uploadFiles = Array.from(e.target.files || [])
  }

  async function uploadDocuments() {
    if (!uploadFiles.length) {
      window.showToast?.('Select files first', 'error')
      return
    }
    uploading = true
    let successCount = 0
    let failCount = 0
    try {
      for (const file of uploadFiles) {
        try {
          await api.documents.upload(file, uploadDocType)
          successCount++
        } catch (error) {
          failCount++
          console.error(`Failed to upload ${file.name}:`, error)
        }
      }
      showUploadModal = false
      uploadFiles = []
      uploadDocType = 'purchase_invoice'
      await loadDocuments()
      if (failCount === 0) {
        window.showToast?.(`${successCount} document${successCount > 1 ? 's' : ''} uploaded, processing started`, 'success')
      } else {
        window.showToast?.(`${successCount} uploaded, ${failCount} failed`, 'error')
      }
    } finally {
      uploading = false
    }
  }

  async function openDetail(doc) {
    detailLoading = true
    showDetailModal = true
    try {
      selectedDoc = await api.documents.get(doc.id)
    } catch (error) {
      window.showToast?.(error.message, 'error')
      showDetailModal = false
    } finally {
      detailLoading = false
    }
  }

  async function viewRaw(doc) {
    try {
      const res = await api.documents.getViewUrl(doc.id)
      window.open(res.url, '_blank')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function reprocessDoc(doc) {
    try {
      await api.documents.reprocess(doc.id)
      await loadDocuments()
      window.showToast?.('Reprocessing started', 'info')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function deleteDoc(doc) {
    if (!confirm(`Delete "${doc.filename}"?`)) return
    try {
      await api.documents.delete(doc.id)
      if (showDetailModal) showDetailModal = false
      await loadDocuments()
      window.showToast?.('Document deleted', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  function formatAmount(amount) {
    if (amount == null) return '—'
    return new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' }).format(amount)
  }

  function formatDate(d) {
    if (!d) return '—'
    return new Date(d).toLocaleDateString('nl-NL')
  }

  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  async function changeDocType(doc, newType) {
    if (newType === doc.doc_type) return
    try {
      const shouldReprocess = doc.status === 'completed' || doc.status === 'failed'
      await api.documents.updateType(doc.id, newType, shouldReprocess)
      await loadDocuments()
      if (shouldReprocess) {
        window.showToast?.('Type changed, reprocessing started', 'info')
      } else {
        window.showToast?.('Type changed', 'success')
      }
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  function parseExtracted(doc) {
    if (!doc?.extracted_data) return null
    try { return JSON.parse(doc.extracted_data) } catch { return null }
  }

  function clearFilters() {
    filterType = ''
    filterStatus = ''
    filterSearch = ''
    filterVendor = ''
    filterDateFrom = ''
    filterDateTo = ''
  }
</script>

<div>
  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
    <h1 class="text-lg font-semibold text-va-text">Documents</h1>
    <Button onclick={() => showUploadModal = true}>
      <span class="icon-[tabler--upload] w-4 h-4 mr-1"></span>
      Upload Document
    </Button>
  </div>

  <!-- Filters -->
  <Card>
    <div class="flex flex-wrap gap-2 items-end">
      <div class="flex flex-col gap-1">
        <label class="text-xs text-va-muted">Search</label>
        <input
          type="text"
          bind:value={filterSearch}
          placeholder="Filename, vendor, ref..."
          class="input input-sm bg-va-canvas border-va-border text-va-text text-xs w-44"
        />
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-va-muted">Type</label>
        <select bind:value={filterType} class="select select-sm bg-va-canvas border-va-border text-va-text text-xs">
          <option value="">All Types</option>
          <option value="sales_invoice">Sales Invoice</option>
          <option value="purchase_invoice">Purchase Invoice</option>
          <option value="tax_letter">Tax Letter</option>
        </select>
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-va-muted">Status</label>
        <select bind:value={filterStatus} class="select select-sm bg-va-canvas border-va-border text-va-text text-xs">
          <option value="">All</option>
          <option value="completed">Completed</option>
          <option value="processing">Processing</option>
          <option value="pending">Pending</option>
          <option value="failed">Failed</option>
        </select>
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-va-muted">Vendor</label>
        <input
          type="text"
          bind:value={filterVendor}
          placeholder="Vendor name..."
          class="input input-sm bg-va-canvas border-va-border text-va-text text-xs w-36"
        />
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-va-muted">From</label>
        <input type="date" bind:value={filterDateFrom} class="input input-sm bg-va-canvas border-va-border text-va-text text-xs" />
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-va-muted">To</label>
        <input type="date" bind:value={filterDateTo} class="input input-sm bg-va-canvas border-va-border text-va-text text-xs" />
      </div>
      <button onclick={clearFilters} class="text-xs text-va-muted hover:text-va-text transition-colors mt-auto pb-1.5">Clear</button>
    </div>
  </Card>

  <!-- Document List -->
  <div class="mt-3">
    <Card>
      {#if loading}
        <div class="flex items-center justify-center h-24">
          <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
        </div>
      {:else if documents.length === 0}
        <div class="text-center py-8">
          <span class="icon-[tabler--file-search] w-8 h-8 text-va-muted mb-3 inline-block"></span>
          <p class="text-va-muted text-sm">No documents found</p>
          <p class="text-va-muted text-xs mt-1">Upload invoices or tax letters to get started</p>
        </div>
      {:else}
        <div class="text-xs text-va-muted mb-2">{total} document{total !== 1 ? 's' : ''}</div>
        <div class="space-y-2">
          {#each documents as doc}
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 bg-va-hover/50 rounded-lg border border-va-border/30 hover:border-va-border transition-all">
              <div class="flex items-start gap-3 min-w-0 flex-1">
                <div class="mt-0.5">
                  {#if doc.doc_type === 'tax_letter'}
                    <span class="icon-[tabler--mail] w-5 h-5 text-va-accent"></span>
                  {:else}
                    <span class="icon-[tabler--file-invoice] w-5 h-5 text-va-accent"></span>
                  {/if}
                </div>
                <div class="min-w-0">
                  <div class="text-sm text-va-text font-medium truncate">{doc.filename}</div>
                  <div class="flex flex-wrap items-center gap-2 mt-1">
                    <select
                      value={doc.doc_type}
                      onchange={(e) => changeDocType(doc, e.target.value)}
                      class="select select-xs bg-transparent border-va-border/50 text-va-accent text-xs py-0 h-5 min-h-0 pr-5 leading-none"
                      onclick={(e) => e.stopPropagation()}
                    >
                      <option value="sales_invoice">Sales Invoice</option>
                      <option value="purchase_invoice">Purchase Invoice</option>
                      <option value="tax_letter">Tax Letter</option>
                    </select>
                    <span class="badge badge-xs badge-soft {statusColors[doc.status]}">{doc.status}</span>
                    <span class="text-xs text-va-muted">{formatFileSize(doc.file_size)}</span>
                    <span class="text-xs text-va-muted">{formatDate(doc.created_at)}</span>
                  </div>
                  {#if doc.status === 'completed'}
                    <div class="flex flex-wrap items-center gap-3 mt-1.5 text-xs text-va-muted">
                      {#if doc.vendor_name}
                        <span><span class="text-va-text">{doc.vendor_name}</span></span>
                      {/if}
                      {#if doc.invoice_number}
                        <span>#{doc.invoice_number}</span>
                      {/if}
                      {#if doc.total_amount != null}
                        <span class="text-va-text font-medium">{formatAmount(doc.total_amount)}</span>
                      {/if}
                      {#if doc.due_date}
                        <span>Due: {formatDate(doc.due_date)}</span>
                      {/if}
                      {#if doc.tax_subject}
                        <span>{doc.tax_subject}</span>
                      {/if}
                    </div>
                    {#if doc.matched_transactions?.length}
                      <div class="flex flex-wrap items-center gap-2 mt-1.5">
                        {#each doc.matched_transactions as txn}
                          <span class="text-xs px-2 py-0.5 rounded-md bg-va-success/10 border border-va-success/30 text-va-success inline-flex items-center gap-1">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                            </svg>
                            {formatAmount(txn.amount)} · {txn.counterparty_name || 'Unknown'} · {formatDate(txn.transaction_date)}
                          </span>
                        {/each}
                      </div>
                    {/if}
                  {/if}
                  {#if doc.status === 'failed' && doc.error_message}
                    <div class="text-xs text-red-400 mt-1 truncate">{doc.error_message}</div>
                  {/if}
                </div>
              </div>
              <div class="flex items-center gap-1 flex-shrink-0">
                {#if doc.status === 'completed'}
                  <button onclick={() => openDetail(doc)} class="p-2 text-va-muted hover:text-va-accent hover:bg-va-accent/10 rounded-lg transition-all" title="View extracted data">
                    <span class="icon-[tabler--file-analytics] w-4 h-4"></span>
                  </button>
                {/if}
                <button onclick={() => viewRaw(doc)} class="p-2 text-va-muted hover:text-va-accent hover:bg-va-accent/10 rounded-lg transition-all" title="View original file">
                  <span class="icon-[tabler--external-link] w-4 h-4"></span>
                </button>
                {#if doc.status === 'failed'}
                  <button onclick={() => reprocessDoc(doc)} class="p-2 text-va-muted hover:text-va-accent hover:bg-va-accent/10 rounded-lg transition-all" title="Retry processing">
                    <span class="icon-[tabler--refresh] w-4 h-4"></span>
                  </button>
                {/if}
                <button onclick={() => deleteDoc(doc)} class="p-2 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded-lg transition-all" title="Delete">
                  <span class="icon-[tabler--trash] w-4 h-4"></span>
                </button>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </Card>
  </div>
</div>

<!-- Upload Modal -->
<Modal bind:show={showUploadModal} title="Upload Document">
  <div class="space-y-4">
    <div>
      <label class="text-xs text-va-muted block mb-1">Document Type</label>
      <select bind:value={uploadDocType} class="select select-sm w-full bg-va-canvas border-va-border text-va-text text-sm">
        <option value="purchase_invoice">Purchase Invoice</option>
        <option value="sales_invoice">Sales Invoice</option>
        <option value="tax_letter">Tax Letter</option>
      </select>
    </div>

    <div>
      <label class="text-xs text-va-muted block mb-1">Files (PDF, PNG, JPEG, WebP, TIFF — max 20MB each)</label>
      <input
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.webp,.tiff,.tif"
        multiple
        onchange={handleFileSelect}
        class="file-input file-input-sm w-full bg-va-canvas border-va-border text-va-text text-sm"
      />
      {#if uploadFiles.length}
        <div class="text-xs text-va-muted mt-1 space-y-0.5">
          {#each uploadFiles as f}
            <p>{f.name} ({formatFileSize(f.size)})</p>
          {/each}
        </div>
      {/if}
    </div>

    <div class="flex gap-3 pt-4 border-t border-va-border">
      <Button onclick={uploadDocuments} loading={uploading}>
        <span class="icon-[tabler--upload] w-4 h-4 mr-1"></span>
        Upload & Process{uploadFiles.length > 1 ? ` (${uploadFiles.length})` : ''}
      </Button>
      <Button variant="secondary" onclick={() => showUploadModal = false}>
        Cancel
      </Button>
    </div>
  </div>
</Modal>

<!-- Detail Modal -->
<Modal bind:show={showDetailModal} title={selectedDoc?.filename || 'Document Details'} size="3xl" onClose={() => selectedDoc = null}>
  {#if detailLoading}
    <div class="flex items-center justify-center h-24">
      <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if selectedDoc}
    {@const extracted = parseExtracted(selectedDoc)}
    <div class="space-y-4">
      <!-- Meta info -->
      <div class="flex flex-wrap gap-2 items-center text-xs">
        <select
          value={selectedDoc.doc_type}
          onchange={(e) => { changeDocType(selectedDoc, e.target.value); selectedDoc = { ...selectedDoc, doc_type: e.target.value } }}
          class="select select-xs bg-transparent border-va-border/50 text-va-accent text-xs py-0 h-5 min-h-0 pr-5 leading-none"
        >
          <option value="sales_invoice">Sales Invoice</option>
          <option value="purchase_invoice">Purchase Invoice</option>
          <option value="tax_letter">Tax Letter</option>
        </select>
        <span class="badge badge-sm badge-soft {statusColors[selectedDoc.status]}">{selectedDoc.status}</span>
        <span class="text-va-muted">{formatFileSize(selectedDoc.file_size)}</span>
        <span class="text-va-muted">Uploaded: {formatDate(selectedDoc.created_at)}</span>
      </div>

      <!-- Extracted data -->
      {#if extracted}
        <div>
          <h4 class="text-sm font-medium text-va-text mb-2">Extracted Information</h4>
          {#if selectedDoc.doc_type === 'tax_letter'}
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {#each Object.entries(extracted) as [key, value]}
                <div class="p-2.5 bg-va-canvas rounded-lg border border-va-border/50">
                  <div class="text-xs text-va-muted capitalize">{key.replace(/_/g, ' ')}</div>
                  <div class="text-sm text-va-text mt-0.5">
                    {#if value == null}—{:else if typeof value === 'number'}{formatAmount(value)}{:else}{value}{/if}
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <!-- Invoice extracted data -->
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
              {#each ['vendor_name', 'customer_name', 'invoice_number', 'invoice_date', 'due_date', 'currency', 'iban', 'payment_reference'] as key}
                {#if extracted[key] != null}
                  <div class="p-2.5 bg-va-canvas rounded-lg border border-va-border/50">
                    <div class="text-xs text-va-muted capitalize">{key.replace(/_/g, ' ')}</div>
                    <div class="text-sm text-va-text mt-0.5">{extracted[key]}</div>
                  </div>
                {/if}
              {/each}
            </div>

            <!-- Totals -->
            <div class="flex flex-wrap gap-4 p-3 bg-va-canvas rounded-lg border border-va-border/50 mb-3">
              {#if extracted.subtotal != null}
                <div>
                  <div class="text-xs text-va-muted">Subtotal</div>
                  <div class="text-sm text-va-text">{formatAmount(extracted.subtotal)}</div>
                </div>
              {/if}
              {#if extracted.vat_amount != null}
                <div>
                  <div class="text-xs text-va-muted">VAT</div>
                  <div class="text-sm text-va-text">{formatAmount(extracted.vat_amount)}</div>
                </div>
              {/if}
              {#if extracted.total_amount != null}
                <div>
                  <div class="text-xs text-va-muted">Total</div>
                  <div class="text-sm text-va-text font-semibold">{formatAmount(extracted.total_amount)}</div>
                </div>
              {/if}
            </div>

            <!-- Line items -->
            {#if extracted.line_items?.length}
              <div>
                <div class="text-xs text-va-muted mb-1.5">Line Items</div>
                <div class="overflow-x-auto">
                  <table class="table table-xs w-full">
                    <thead>
                      <tr class="text-va-muted">
                        <th class="text-xs">Description</th>
                        <th class="text-xs text-right">Qty</th>
                        <th class="text-xs text-right">Unit Price</th>
                        <th class="text-xs text-right">VAT %</th>
                        <th class="text-xs text-right">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each extracted.line_items as item}
                        <tr class="text-va-text">
                          <td class="text-xs">{item.description || '—'}</td>
                          <td class="text-xs text-right">{item.quantity ?? '—'}</td>
                          <td class="text-xs text-right">{item.unit_price != null ? formatAmount(item.unit_price) : '—'}</td>
                          <td class="text-xs text-right">{item.vat_rate ?? '—'}%</td>
                          <td class="text-xs text-right">{item.line_total != null ? formatAmount(item.line_total) : '—'}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              </div>
            {/if}
          {/if}
        </div>
      {/if}

      <!-- Matched Transactions -->
      {#if selectedDoc.matched_transactions?.length}
        <div>
          <h4 class="text-sm font-medium text-va-text mb-2">Matched Transactions</h4>
          <div class="space-y-2">
            {#each selectedDoc.matched_transactions as txn}
              <div class="flex items-center justify-between p-2.5 bg-va-canvas rounded-lg border border-va-success/30">
                <div class="flex items-center gap-3">
                  <span class="text-sm font-medium {txn.amount >= 0 ? 'text-va-success' : 'text-va-danger'}">{formatAmount(txn.amount)}</span>
                  <span class="text-xs text-va-muted">{txn.counterparty_name || 'Unknown'}</span>
                  <span class="text-xs text-va-muted">{formatDate(txn.transaction_date)}</span>
                </div>
                {#if txn.description}
                  <span class="text-xs text-va-muted max-w-[200px] truncate" title={txn.description}>{txn.description}</span>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- OCR text (collapsible) -->
      {#if selectedDoc.ocr_text}
        <details class="group">
          <summary class="text-xs text-va-muted cursor-pointer hover:text-va-text transition-colors">
            <span class="icon-[tabler--chevron-right] w-3 h-3 inline-block group-open:rotate-90 transition-transform"></span>
            Raw OCR Text
          </summary>
          <pre class="mt-2 p-3 bg-va-canvas rounded-lg border border-va-border/50 text-xs text-va-muted overflow-x-auto max-h-64 whitespace-pre-wrap">{selectedDoc.ocr_text}</pre>
        </details>
      {/if}

      <!-- Actions -->
      <div class="flex gap-2 pt-3 border-t border-va-border">
        <Button variant="secondary" onclick={() => viewRaw(selectedDoc)}>
          <span class="icon-[tabler--external-link] w-4 h-4 mr-1"></span>
          View Original
        </Button>
        {#if selectedDoc.status === 'failed' || selectedDoc.status === 'completed'}
          <Button variant="secondary" onclick={() => { reprocessDoc(selectedDoc); showDetailModal = false }}>
            <span class="icon-[tabler--refresh] w-4 h-4 mr-1"></span>
            Reprocess
          </Button>
        {/if}
        <Button variant="danger" onclick={() => deleteDoc(selectedDoc)}>
          <span class="icon-[tabler--trash] w-4 h-4 mr-1"></span>
          Delete
        </Button>
      </div>
    </div>
  {/if}
</Modal>
