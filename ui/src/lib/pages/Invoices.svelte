<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Button from '../components/Button.svelte'
  import Modal from '../components/Modal.svelte'
  import Input from '../components/Input.svelte'
  import api from '../api.js'
  import { getPrivacyMode } from '../privacy.svelte.js'

  let privacyOn = $derived(getPrivacyMode())

  let invoices = $state([])
  let clients = $state([])
  let loading = $state(true)
  let showModal = $state(false)
  let saving = $state(false)
  let editingInvoice = $state(null)
  let downloadingPdf = $state(null)

  // Form state
  let form = $state({
    client_id: '',
    invoice_number: '',
    invoice_date: new Date().toISOString().split('T')[0],
    due_date: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    notes: '',
    items: [{ description: '', quantity: 1, unit_price: 0, vat_rate: 21 }]
  })

  // Computed: selected client details
  let selectedClient = $derived(
    form.client_id ? clients.find(c => c.id === parseInt(form.client_id)) : null
  )

  // Computed: live totals
  let itemTotals = $derived(
    form.items.map(item => {
      const qty = parseFloat(item.quantity) || 0
      const price = parseFloat(item.unit_price) || 0
      return qty * price
    })
  )

  let subtotal = $derived(itemTotals.reduce((sum, t) => sum + t, 0))

  let vatTotal = $derived(
    form.items.reduce((sum, item, i) => {
      const rate = parseFloat(item.vat_rate) || 0
      return sum + (itemTotals[i] * rate / 100)
    }, 0)
  )

  let grandTotal = $derived(subtotal + vatTotal)

  // Helper: get client name by id
  function getClientName(clientId) {
    const client = clients.find(c => c.id === clientId)
    return client ? client.name : '-'
  }

  onMount(async () => {
    await Promise.all([loadInvoices(), loadClients()])
  })

  async function loadInvoices() {
    loading = true
    try {
      invoices = await api.invoices.list()
    } catch (error) {
      console.error('Failed to load invoices:', error)
    } finally {
      loading = false
    }
  }

  async function loadClients() {
    try {
      clients = await api.clients.list()
    } catch (error) {
      console.error('Failed to load clients:', error)
    }
  }

  function addItem() {
    form.items = [...form.items, { description: '', quantity: 1, unit_price: 0, vat_rate: 21 }]
  }

  function removeItem(index) {
    form.items = form.items.filter((_, i) => i !== index)
  }

  async function openCreateModal() {
    editingInvoice = null
    resetForm()
    showModal = true
    // Pre-fill invoice number
    try {
      const result = await api.invoices.nextNumber()
      form.invoice_number = result.invoice_number
    } catch (error) {
      console.error('Failed to get next invoice number:', error)
    }
  }

  async function openEditModal(invoice) {
    editingInvoice = invoice
    // Fetch full invoice with items
    try {
      const full = await api.invoices.get(invoice.id)
      form = {
        client_id: String(full.client_id),
        invoice_number: full.invoice_number,
        invoice_date: full.invoice_date,
        due_date: full.due_date,
        notes: full.notes || '',
        items: full.items.length > 0
          ? full.items.map(item => ({
              description: item.description,
              quantity: parseFloat(item.quantity),
              unit_price: parseFloat(item.unit_price),
              vat_rate: parseFloat(item.vat_rate)
            }))
          : [{ description: '', quantity: 1, unit_price: 0, vat_rate: 21 }]
      }
      showModal = true
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function saveInvoice() {
    if (!form.client_id || !form.invoice_number) {
      window.showToast?.('Please fill in client and invoice number', 'error')
      return
    }

    const hasValidItem = form.items.some(item => item.description.trim())
    if (!hasValidItem) {
      window.showToast?.('Please add at least one line item with a description', 'error')
      return
    }

    saving = true
    try {
      const payload = {
        ...form,
        client_id: parseInt(form.client_id),
        items: form.items
          .filter(item => item.description.trim())
          .map(item => ({
            description: item.description,
            quantity: parseFloat(item.quantity) || 0,
            unit_price: parseFloat(item.unit_price) || 0,
            vat_rate: parseFloat(item.vat_rate) || 0
          }))
      }

      if (editingInvoice) {
        await api.invoices.update(editingInvoice.id, payload)
        window.showToast?.('Invoice updated successfully', 'success')
      } else {
        await api.invoices.create(payload)
        window.showToast?.('Invoice created successfully', 'success')
      }

      showModal = false
      resetForm()
      await loadInvoices()
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      saving = false
    }
  }

  async function downloadPdf(invoice) {
    downloadingPdf = invoice.id
    try {
      await api.invoices.downloadPdf(invoice.id)
    } catch (error) {
      window.showToast?.('Failed to download PDF', 'error')
    } finally {
      downloadingPdf = null
    }
  }

  async function revertToDraft(invoice) {
    try {
      await api.invoices.update(invoice.id, { status: 'draft' })
      await loadInvoices()
      window.showToast?.('Invoice reverted to draft', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function markSent(invoice) {
    try {
      await api.invoices.send(invoice.id)
      await loadInvoices()
      window.showToast?.('Invoice marked as sent', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function markPaid(invoice) {
    try {
      await api.invoices.markPaid(invoice.id)
      await loadInvoices()
      window.showToast?.('Invoice marked as paid', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function deleteInvoice(invoice) {
    if (!confirm(`Delete invoice ${invoice.invoice_number}?`)) return
    try {
      await api.invoices.delete(invoice.id)
      await loadInvoices()
      window.showToast?.('Invoice deleted', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  function resetForm() {
    form = {
      client_id: '',
      invoice_number: '',
      invoice_date: new Date().toISOString().split('T')[0],
      due_date: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
      notes: '',
      items: [{ description: '', quantity: 1, unit_price: 0, vat_rate: 21 }]
    }
    editingInvoice = null
  }

  function formatCurrency(amount) {
    return new Intl.NumberFormat('nl-NL', {
      style: 'currency',
      currency: 'EUR'
    }).format(amount)
  }

  function formatDate(dateStr) {
    return new Date(dateStr).toLocaleDateString('nl-NL', {
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    })
  }

  function getStatusColor(status) {
    const colors = {
      draft: 'bg-va-muted/20 text-va-muted border-va-muted/30',
      sent: 'bg-va-accent/20 text-va-accent border-va-accent/30',
      paid: 'bg-va-success/20 text-va-success border-va-success/30',
      overdue: 'bg-va-danger/20 text-va-danger border-va-danger/30',
      cancelled: 'bg-va-muted/10 text-va-muted border-va-border'
    }
    return colors[status] || 'bg-va-muted/20 text-va-muted border-va-muted/30'
  }
</script>

<div>
  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
    <h1 class="text-lg font-semibold text-va-text">Invoices</h1>
    <Button onclick={openCreateModal}>
      New Invoice
    </Button>
  </div>

  <Card>
    {#if loading}
      <div class="flex items-center justify-center h-24">
        <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    {:else if invoices.length === 0}
      <div class="text-center py-8">
        <div class="text-4xl mb-3">📄</div>
        <p class="text-va-muted text-sm">No invoices yet</p>
        <p class="text-va-muted text-sm mt-1">Create your first invoice to get started</p>
      </div>
    {:else}
      <div class="overflow-x-auto rounded-lg">
        <table class="w-full min-w-[700px]">
          <thead>
            <tr class="border-b border-va-border">
              <th class="text-left py-3 px-3 text-sm text-va-muted font-medium">Invoice #</th>
              <th class="text-left py-3 px-3 text-sm text-va-muted font-medium">Client</th>
              <th class="text-left py-3 px-3 text-sm text-va-muted font-medium">Date</th>
              <th class="text-left py-3 px-3 text-sm text-va-muted font-medium">Due Date</th>
              <th class="text-left py-3 px-3 text-sm text-va-muted font-medium">Status</th>
              <th class="text-right py-3 px-3 text-sm text-va-muted font-medium">Amount</th>
              <th class="text-right py-3 px-3 text-sm text-va-muted font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each invoices as invoice}
              <tr class="border-b border-va-border/30 hover:bg-va-hover/50 transition-colors group">
                <td class="py-3 px-3 text-sm text-va-text font-medium">
                  {invoice.invoice_number}
                </td>
                <td class="py-3 px-3 text-sm text-va-muted" class:privacy-blur={privacyOn}>
                  {getClientName(invoice.client_id)}
                </td>
                <td class="py-3 px-3 text-sm text-va-muted">
                  {formatDate(invoice.invoice_date)}
                </td>
                <td class="py-3 px-3 text-sm text-va-muted">
                  {formatDate(invoice.due_date)}
                </td>
                <td class="py-3 px-3">
                  <span class="px-2 py-1 rounded-md text-xs font-medium border {getStatusColor(invoice.status)}">
                    {invoice.status}
                  </span>
                </td>
                <td class="py-3 px-3 text-right text-sm font-medium text-va-text">
                  {formatCurrency(invoice.total_amount)}
                </td>
                <td class="py-3 px-3 text-right">
                  <div class="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onclick={() => openEditModal(invoice)}
                      class="p-1.5 rounded-md text-va-muted hover:text-va-accent hover:bg-va-accent/10 transition-colors"
                      title="Edit"
                    >
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                    <button
                      onclick={() => downloadPdf(invoice)}
                      class="p-1.5 rounded-md text-va-muted hover:text-va-accent hover:bg-va-accent/10 transition-colors"
                      title="Download PDF"
                      disabled={downloadingPdf === invoice.id}
                    >
                      {#if downloadingPdf === invoice.id}
                        <div class="w-4 h-4 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
                      {:else}
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                      {/if}
                    </button>
                    {#if invoice.status === 'draft'}
                      <button
                        onclick={() => markSent(invoice)}
                        class="p-1.5 rounded-md text-va-muted hover:text-va-accent hover:bg-va-accent/10 transition-colors"
                        title="Mark as Sent"
                      >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                        </svg>
                      </button>
                    {/if}
                    {#if invoice.status === 'sent' || invoice.status === 'overdue'}
                      <button
                        onclick={() => markPaid(invoice)}
                        class="p-1.5 rounded-md text-va-muted hover:text-va-success hover:bg-va-success/10 transition-colors"
                        title="Mark as Paid"
                      >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                      </button>
                    {/if}
                    {#if invoice.status !== 'draft'}
                      <button
                        onclick={() => revertToDraft(invoice)}
                        class="p-1.5 rounded-md text-va-muted hover:text-va-warning hover:bg-va-warning/10 transition-colors"
                        title="Revert to Draft"
                      >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                        </svg>
                      </button>
                    {/if}
                    {#if invoice.status === 'draft'}
                      <button
                        onclick={() => deleteInvoice(invoice)}
                        class="p-1.5 rounded-md text-va-muted hover:text-va-danger hover:bg-va-danger/10 transition-colors"
                        title="Delete"
                      >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    {/if}
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </Card>
</div>

<!-- Create / Edit Invoice Modal -->
<Modal bind:show={showModal} title={editingInvoice ? `Edit Invoice ${editingInvoice.invoice_number}` : 'Create Invoice'} size="4xl" onClose={resetForm}>
  <div class="space-y-5">

    <!-- Invoice Details Row -->
    <div>
      <h4 class="text-xs uppercase tracking-wider text-va-muted mb-3 font-medium">Invoice Details</h4>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label class="block text-sm text-va-muted mb-1.5">Invoice Number <span class="text-va-danger">*</span></label>
          <input
            type="text"
            bind:value={form.invoice_number}
            placeholder="INV-2026-001"
            class="input input-sm bg-va-canvas border-va-border text-va-text"
          />
        </div>
        <div>
          <label class="block text-sm text-va-muted mb-1.5">Invoice Date <span class="text-va-danger">*</span></label>
          <input
            type="date"
            bind:value={form.invoice_date}
            class="input input-sm bg-va-canvas border-va-border text-va-text"
          />
        </div>
        <div>
          <label class="block text-sm text-va-muted mb-1.5">Due Date <span class="text-va-danger">*</span></label>
          <input
            type="date"
            bind:value={form.due_date}
            class="input input-sm bg-va-canvas border-va-border text-va-text"
          />
        </div>
      </div>
    </div>

    <!-- Client Selection -->
    <div>
      <h4 class="text-xs uppercase tracking-wider text-va-muted mb-3 font-medium">Client</h4>
      <select bind:value={form.client_id} class="input input-sm bg-va-canvas border-va-border text-va-text mb-2">
        <option value="">Select a client...</option>
        {#each clients as client}
          <option value={client.id}>{client.name}</option>
        {/each}
      </select>

      {#if selectedClient}
        <div class="rounded-lg border border-va-border bg-va-canvas/50 p-3 flex items-start gap-3">
          <div class="w-8 h-8 rounded-lg bg-va-accent/15 flex items-center justify-center text-va-accent text-sm font-bold shrink-0">
            {selectedClient.name.charAt(0).toUpperCase()}
          </div>
          <div class="min-w-0 text-sm">
            <p class="font-medium text-va-text">{selectedClient.name}</p>
            <div class="text-va-muted text-xs mt-0.5 space-y-0.5">
              {#if selectedClient.address}
                <p>{selectedClient.address}</p>
              {/if}
              {#if selectedClient.postal_code || selectedClient.city}
                <p>{[selectedClient.postal_code, selectedClient.city].filter(Boolean).join(', ')}</p>
              {/if}
              {#if selectedClient.country}
                <p>{selectedClient.country}</p>
              {/if}
            </div>
            <div class="flex flex-wrap gap-x-4 gap-y-1 mt-1.5 text-xs">
              {#if selectedClient.vat_number}
                <span class="text-va-muted">VAT: <span class="text-va-text">{selectedClient.vat_number}</span></span>
              {/if}
              {#if selectedClient.chamber_of_commerce}
                <span class="text-va-muted">KvK: <span class="text-va-text">{selectedClient.chamber_of_commerce}</span></span>
              {/if}
              {#if selectedClient.email}
                <span class="text-va-muted">Email: <span class="text-va-text">{selectedClient.email}</span></span>
              {/if}
            </div>
          </div>
        </div>
      {/if}
    </div>

    <!-- Line Items -->
    <div>
      <h4 class="text-xs uppercase tracking-wider text-va-muted mb-3 font-medium">Line Items</h4>
      <div class="rounded-lg border border-va-border overflow-x-auto">
        <table class="w-full min-w-[500px]">
          <thead>
            <tr class="bg-va-canvas/50">
              <th class="text-left py-2 px-3 text-xs text-va-muted font-medium">Description</th>
              <th class="text-center py-2 px-3 text-xs text-va-muted font-medium w-20">Qty</th>
              <th class="text-right py-2 px-3 text-xs text-va-muted font-medium w-28">Unit Price</th>
              <th class="text-center py-2 px-3 text-xs text-va-muted font-medium w-20">VAT %</th>
              <th class="text-right py-2 px-3 text-xs text-va-muted font-medium w-28">Total</th>
              <th class="w-10"></th>
            </tr>
          </thead>
          <tbody>
            {#each form.items as item, index}
              <tr class="border-t border-va-border/50">
                <td class="py-1.5 px-2">
                  <input
                    type="text"
                    bind:value={item.description}
                    placeholder="Service or product description"
                    class="input input-xs bg-va-canvas border-va-border text-va-text"
                  />
                </td>
                <td class="py-1.5 px-2">
                  <input
                    type="number"
                    bind:value={item.quantity}
                    placeholder="1"
                    class="input input-xs bg-va-canvas border-va-border text-va-text text-center"
                    min="0"
                    step="0.01"
                  />
                </td>
                <td class="py-1.5 px-2">
                  <input
                    type="number"
                    bind:value={item.unit_price}
                    placeholder="0.00"
                    class="input input-xs bg-va-canvas border-va-border text-va-text text-right"
                    min="0"
                    step="0.01"
                  />
                </td>
                <td class="py-1.5 px-2">
                  <input
                    type="number"
                    bind:value={item.vat_rate}
                    placeholder="21"
                    class="input input-xs bg-va-canvas border-va-border text-va-text text-center"
                    min="0"
                    step="1"
                  />
                </td>
                <td class="py-1.5 px-2 text-right text-sm text-va-text font-medium whitespace-nowrap">
                  {formatCurrency(itemTotals[index] || 0)}
                </td>
                <td class="py-1.5 px-1">
                  {#if form.items.length > 1}
                    <button
                      onclick={() => removeItem(index)}
                      class="p-1 rounded text-va-muted hover:text-va-danger hover:bg-va-danger/10 transition-colors"
                      title="Remove item"
                    >
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <div class="border-t border-va-border/50 px-3 py-2">
          <button onclick={addItem} class="text-xs text-va-accent hover:text-va-accent/80 font-medium transition-colors">
            + Add line item
          </button>
        </div>
      </div>
    </div>

    <!-- Totals -->
    <div class="flex justify-end">
      <div class="w-full sm:w-72 space-y-1.5">
        <div class="flex justify-between text-sm">
          <span class="text-va-muted">Subtotal</span>
          <span class="text-va-text">{formatCurrency(subtotal)}</span>
        </div>
        <div class="flex justify-between text-sm">
          <span class="text-va-muted">VAT</span>
          <span class="text-va-text">{formatCurrency(vatTotal)}</span>
        </div>
        <div class="border-t border-va-border pt-1.5">
          <div class="flex justify-between text-base font-semibold">
            <span class="text-va-text">Total</span>
            <span class="text-va-accent">{formatCurrency(grandTotal)}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Notes -->
    <div>
      <h4 class="text-xs uppercase tracking-wider text-va-muted mb-3 font-medium">Notes</h4>
      <textarea
        bind:value={form.notes}
        placeholder="Payment terms, bank details, or other notes..."
        rows="3"
        class="input input-sm bg-va-canvas border-va-border text-va-text resize-none"
      ></textarea>
    </div>
  </div>

  <!-- Actions -->
  <div class="flex flex-col-reverse sm:flex-row items-stretch sm:items-center justify-between gap-2 mt-5 pt-4 border-t border-va-border">
    <Button variant="secondary" onclick={() => showModal = false}>
      Cancel
    </Button>
    <Button onclick={saveInvoice} loading={saving}>
      {editingInvoice ? 'Save Changes' : 'Create Invoice'}
    </Button>
  </div>
</Modal>
