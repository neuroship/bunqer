<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Button from '../components/Button.svelte'
  import Input from '../components/Input.svelte'
  import api from '../api.js'

  let accounts = $state([])
  let counterparties = $state([])
  let loading = $state(true)
  let submitting = $state(false)
  let lastDraft = $state(null)
  let lastSchedule = $state(null)
  let error = $state('')
  let scheduleMode = $state(false)
  let schedules = $state([])
  let schedulesLoading = $state(false)
  let cancellingId = $state(null)

  let form = $state({
    account_id: '',
    amount: '',
    currency: 'EUR',
    counterparty_iban: '',
    counterparty_name: '',
    description: '',
    time_start: '',
    time_end: '',
    recurrence_unit: 'MONTHLY',
    recurrence_size: 1
  })

  let nameQuery = $derived(form.counterparty_name.trim().toLowerCase())
  let ibanQuery = $derived(form.counterparty_iban.replace(/\s+/g, '').toLowerCase())
  let showSuggestions = $state(false)

  let filteredCounterparties = $derived.by(() => {
    if (!counterparties.length) return []
    const q = nameQuery
    const qIban = ibanQuery
    if (!q && !qIban) return counterparties.slice(0, 8)
    return counterparties
      .filter(c => {
        const nameMatch = q ? c.name.toLowerCase().includes(q) : true
        const ibanMatch = qIban ? c.iban.toLowerCase().includes(qIban) : true
        return nameMatch && ibanMatch
      })
      .slice(0, 8)
  })

  function isValidIban(iban) {
    const cleaned = (iban || '').replace(/\s+/g, '').toUpperCase()
    return /^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$/.test(cleaned)
  }

  let amountValid = $derived(parseFloat(form.amount) > 0)
  let ibanValid = $derived(isValidIban(form.counterparty_iban))
  let nameValid = $derived(form.counterparty_name.trim().length > 0)
  let accountValid = $derived(!!form.account_id)
  let scheduleStartValid = $derived(!scheduleMode || !!form.time_start)
  let recurrenceSizeValid = $derived(!scheduleMode || (Number(form.recurrence_size) >= 1))
  let scheduleEndValid = $derived(
    !scheduleMode || !form.time_end || (new Date(form.time_end) > new Date(form.time_start))
  )
  let canSubmit = $derived(
    amountValid && ibanValid && nameValid && accountValid && !submitting &&
    scheduleStartValid && recurrenceSizeValid && scheduleEndValid
  )

  let selectedAccount = $derived(
    accounts.find(a => String(a.id) === String(form.account_id))
  )

  onMount(async () => {
    try {
      const [accs, cps] = await Promise.all([
        api.setup.listAccounts(),
        api.payments.listCounterparties()
      ])
      accounts = accs.filter(a => a.monetary_account_id)
      counterparties = cps
      if (accounts.length === 1) {
        form.account_id = accounts[0].id
        await loadSchedules()
      }
    } catch (e) {
      console.error('Failed to load payments page:', e)
      error = e.message || 'Failed to load data'
    } finally {
      loading = false
    }
  })

  async function loadSchedules() {
    if (!form.account_id) {
      schedules = []
      return
    }
    schedulesLoading = true
    try {
      schedules = await api.payments.listSchedules(Number(form.account_id))
    } catch (e) {
      console.error('Failed to load schedules:', e)
      schedules = []
    } finally {
      schedulesLoading = false
    }
  }

  $effect(() => {
    if (form.account_id) loadSchedules()
  })

  function toBunqDt(localDt) {
    // local datetime-local input → UTC ISO without timezone (FastAPI parses to naive UTC)
    const d = new Date(localDt)
    return d.toISOString()
  }

  function formatScheduleDt(s) {
    if (!s) return ''
    // bunq returns "YYYY-MM-DD HH:MM:SS.ffffff" UTC
    const iso = s.replace(' ', 'T') + 'Z'
    const d = new Date(iso)
    if (isNaN(d)) return s
    return d.toLocaleString()
  }

  async function cancelSchedule(id) {
    if (id == null || !form.account_id) return
    cancellingId = id
    try {
      await api.payments.deleteSchedule(id, Number(form.account_id))
      window.showToast?.('Scheduled payment cancelled.', 'success')
      await loadSchedules()
    } catch (e) {
      window.showToast?.(e.message || 'Cancel failed', 'error')
    } finally {
      cancellingId = null
    }
  }

  function selectCounterparty(cp) {
    form.counterparty_name = cp.name
    form.counterparty_iban = cp.iban
    showSuggestions = false
  }

  async function submit() {
    if (!canSubmit) return
    error = ''
    submitting = true
    try {
      const base = {
        account_id: Number(form.account_id),
        amount: form.amount,
        currency: form.currency,
        counterparty_iban: form.counterparty_iban.replace(/\s+/g, '').toUpperCase(),
        counterparty_name: form.counterparty_name.trim(),
        description: form.description
      }
      if (scheduleMode) {
        const payload = {
          ...base,
          time_start: toBunqDt(form.time_start),
          time_end: form.time_end ? toBunqDt(form.time_end) : null,
          recurrence_unit: form.recurrence_unit,
          recurrence_size: Number(form.recurrence_size)
        }
        lastSchedule = await api.payments.createSchedule(payload)
        window.showToast?.('Scheduled payment created.', 'success')
        await loadSchedules()
      } else {
        lastDraft = await api.payments.createDraft(base)
        window.showToast?.('Draft payment created. Approve in the bunq app.', 'success')
      }
      form.amount = ''
      form.description = ''
      form.counterparty_iban = ''
      form.counterparty_name = ''
      form.time_start = ''
      form.time_end = ''
      counterparties = await api.payments.listCounterparties()
    } catch (e) {
      error = e.message || 'Failed to create payment'
      window.showToast?.(error, 'error')
    } finally {
      submitting = false
    }
  }

  async function refreshStatus() {
    if (!lastDraft) return
    try {
      const data = await api.payments.getDraft(lastDraft.draft_payment_id, lastDraft.account_id)
      lastDraft = { ...lastDraft, status: data.status }
      window.showToast?.(`Status: ${data.status}`, 'info')
    } catch (e) {
      window.showToast?.(e.message, 'error')
    }
  }

  function formatIban(iban) {
    return (iban || '').replace(/\s+/g, '').replace(/(.{4})/g, '$1 ').trim()
  }
</script>

<div>
  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
    <div>
      <h1 class="text-lg font-semibold text-va-text">Payments</h1>
      <p class="text-xs text-va-muted mt-0.5">
        Draft payments need bunq-app approval. Scheduled payments auto-execute.
      </p>
    </div>
  </div>

  {#if loading}
    <Card>
      <div class="flex items-center justify-center h-24">
        <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    </Card>
  {:else if accounts.length === 0}
    <Card>
      <div class="text-center py-8">
        <span class="icon-[tabler--alert-circle] w-8 h-8 text-va-muted mb-3 inline-block"></span>
        <p class="text-va-muted text-sm">No bunq-linked accounts.</p>
        <p class="text-va-muted text-sm mt-1">Set up a bunq integration first in the Setup tab.</p>
      </div>
    </Card>
  {:else}
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="lg:col-span-2">
        <Card title={scheduleMode ? 'New Scheduled Payment' : 'New Draft Payment'}>
          <div class="mb-3 flex items-center justify-between gap-3">
            <div class="flex-1">
              <label class="block text-sm text-va-muted mb-1.5">
                From account <span class="text-va-danger">*</span>
              </label>
              <select
                bind:value={form.account_id}
                class="select select-sm bg-va-canvas border-va-border text-va-text w-full"
              >
                <option value="">Select an account</option>
                {#each accounts as acc}
                  <option value={acc.id}>
                    {acc.name}{acc.iban ? ` — ${formatIban(acc.iban)}` : ''}
                  </option>
                {/each}
              </select>
            </div>
            <label class="flex items-center gap-2 mt-6 cursor-pointer">
              <input type="checkbox" bind:checked={scheduleMode} class="checkbox checkbox-sm" />
              <span class="text-sm text-va-text">Schedule recurring</span>
            </label>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div class="sm:col-span-2">
              <Input
                label="Amount"
                type="number"
                bind:value={form.amount}
                placeholder="0.00"
                required
                error={form.amount && !amountValid ? 'Must be > 0' : ''}
              />
            </div>
            <div class="mb-3">
              <label class="block text-sm text-va-muted mb-1.5">Currency</label>
              <select
                bind:value={form.currency}
                class="select select-sm bg-va-canvas border-va-border text-va-text w-full"
              >
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
                <option value="GBP">GBP</option>
              </select>
            </div>
          </div>

          <div class="mb-3 payments-autocomplete relative">
            <label class="block text-sm text-va-muted mb-1.5">
              Counterparty name <span class="text-va-danger">*</span>
            </label>
            <input
              type="text"
              bind:value={form.counterparty_name}
              onfocus={() => showSuggestions = true}
              oninput={() => showSuggestions = true}
              placeholder="Recipient name"
              class="input input-sm bg-va-canvas border-va-border text-va-text w-full {form.counterparty_name && !nameValid ? 'border-va-danger' : ''}"
            />
            {#if showSuggestions && filteredCounterparties.length}
              <div class="absolute z-20 left-0 right-0 mt-1 bg-va-subtle border border-va-border rounded-lg shadow-soft max-h-64 overflow-y-auto">
                {#each filteredCounterparties as cp}
                  <button
                    type="button"
                    onmousedown={(e) => { e.preventDefault(); selectCounterparty(cp) }}
                    class="w-full text-left px-3 py-2 hover:bg-va-hover transition-colors border-b border-va-border/30 last:border-b-0"
                  >
                    <div class="text-sm text-va-text truncate">{cp.name}</div>
                    <div class="text-xs text-va-muted truncate">{formatIban(cp.iban)} · {cp.transaction_count}×</div>
                  </button>
                {/each}
              </div>
            {/if}
          </div>

          <Input
            label="Counterparty IBAN"
            bind:value={form.counterparty_iban}
            placeholder="NL00BUNQ0000000000"
            required
            error={form.counterparty_iban && !ibanValid ? 'Invalid IBAN format' : ''}
          />

          <Input
            label="Description"
            bind:value={form.description}
            placeholder="What is this payment for? (max 140 chars)"
          />

          {#if scheduleMode}
            <div class="mt-3 p-3 rounded-lg bg-va-canvas border border-va-border/50 space-y-3">
              <div class="text-xs text-va-muted">
                <span class="icon-[tabler--calendar-time] w-3.5 h-3.5 inline-block align-text-bottom mr-1"></span>
                Auto-executes per schedule. No bunq-app approval needed.
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                  <label class="block text-sm text-va-muted mb-1.5">
                    First execution <span class="text-va-danger">*</span>
                  </label>
                  <input
                    type="datetime-local"
                    bind:value={form.time_start}
                    class="input input-sm bg-va-canvas border-va-border text-va-text w-full"
                  />
                </div>
                <div>
                  <label class="block text-sm text-va-muted mb-1.5">End (optional)</label>
                  <input
                    type="datetime-local"
                    bind:value={form.time_end}
                    class="input input-sm bg-va-canvas border-va-border text-va-text w-full {form.time_end && !scheduleEndValid ? 'border-va-danger' : ''}"
                  />
                </div>
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                  <label class="block text-sm text-va-muted mb-1.5">Every</label>
                  <input
                    type="number"
                    min="1"
                    bind:value={form.recurrence_size}
                    class="input input-sm bg-va-canvas border-va-border text-va-text w-full"
                  />
                </div>
                <div>
                  <label class="block text-sm text-va-muted mb-1.5">Unit</label>
                  <select
                    bind:value={form.recurrence_unit}
                    class="select select-sm bg-va-canvas border-va-border text-va-text w-full"
                  >
                    <option value="DAILY">Day(s)</option>
                    <option value="WEEKLY">Week(s)</option>
                    <option value="MONTHLY">Month(s)</option>
                    <option value="YEARLY">Year(s)</option>
                    <option value="HOURLY">Hour(s)</option>
                  </select>
                </div>
              </div>
              {#if form.time_end && !scheduleEndValid}
                <div class="text-xs text-va-danger">End must be after first execution.</div>
              {/if}
            </div>
          {/if}

          {#if selectedAccount}
            <div class="mt-3 p-3 rounded-lg bg-va-canvas border border-va-border/50 text-xs text-va-muted space-y-0.5">
              <div>Sending from <span class="text-va-text">{selectedAccount.name}</span></div>
              {#if selectedAccount.iban}
                <div>IBAN: <span class="text-va-text font-mono">{formatIban(selectedAccount.iban)}</span></div>
              {/if}
              <div class="pt-1">
                <span class="icon-[tabler--info-circle] w-3.5 h-3.5 inline-block align-text-bottom mr-1"></span>
                {scheduleMode
                  ? 'Scheduled payments auto-execute on bunq side. Cancel here to stop them.'
                  : 'After creating, open the bunq app to approve the draft payment.'}
              </div>
            </div>
          {/if}

          {#if error}
            <div class="mt-3 p-3 rounded-lg bg-va-danger/10 border border-va-danger/30 text-sm text-va-danger">
              {error}
            </div>
          {/if}

          <div class="flex gap-3 mt-5 pt-4 border-t border-va-border">
            <Button onclick={submit} loading={submitting} disabled={!canSubmit}>
              {scheduleMode ? 'Create Scheduled Payment' : 'Create Draft Payment'}
            </Button>
          </div>
        </Card>

        <div class="mt-4">
          <Card title="Existing Scheduled Payments">
            {#if !form.account_id}
              <p class="text-sm text-va-muted">Select an account to view schedules.</p>
            {:else if schedulesLoading}
              <div class="flex items-center gap-2 text-sm text-va-muted">
                <div class="w-4 h-4 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
                Loading…
              </div>
            {:else if schedules.length === 0}
              <p class="text-sm text-va-muted">No scheduled payments on this account.</p>
            {:else}
              <div class="space-y-2">
                {#each schedules as s}
                  <div class="p-3 rounded-lg bg-va-canvas border border-va-border/50 flex items-start justify-between gap-3">
                    <div class="text-sm min-w-0 flex-1">
                      <div class="text-va-text truncate">
                        {s.amount} {s.currency} → {s.counterparty_name || s.counterparty_iban || '—'}
                      </div>
                      <div class="text-xs text-va-muted truncate">
                        {s.counterparty_iban ? formatIban(s.counterparty_iban) : ''}
                      </div>
                      <div class="text-xs text-va-muted mt-1">
                        Every {s.recurrence_size} {s.recurrence_unit?.toLowerCase()} · next {formatScheduleDt(s.time_start)}
                        {#if s.time_end}· until {formatScheduleDt(s.time_end)}{/if}
                      </div>
                      {#if s.description}
                        <div class="text-xs text-va-muted truncate mt-0.5">{s.description}</div>
                      {/if}
                      {#if s.status}
                        <div class="text-xs text-va-muted mt-0.5">Status: {s.status}</div>
                      {/if}
                    </div>
                    <Button
                      variant="secondary"
                      onclick={() => cancelSchedule(s.id)}
                      loading={cancellingId === s.id}
                      disabled={cancellingId !== null}
                    >
                      Cancel
                    </Button>
                  </div>
                {/each}
              </div>
            {/if}
          </Card>
        </div>
      </div>

      <div>
        <Card title="Last Draft">
          {#if !lastDraft}
            <p class="text-sm text-va-muted">No draft created yet in this session.</p>
          {:else}
            <div class="space-y-2 text-sm">
              <div>
                <div class="text-xs text-va-muted">Draft ID</div>
                <div class="text-va-text font-mono">#{lastDraft.draft_payment_id}</div>
              </div>
              <div>
                <div class="text-xs text-va-muted">Amount</div>
                <div class="text-va-text">{lastDraft.amount} {lastDraft.currency}</div>
              </div>
              <div>
                <div class="text-xs text-va-muted">To</div>
                <div class="text-va-text">{lastDraft.counterparty_name}</div>
                <div class="text-xs text-va-muted font-mono">{formatIban(lastDraft.counterparty_iban)}</div>
              </div>
              {#if lastDraft.description}
                <div>
                  <div class="text-xs text-va-muted">Description</div>
                  <div class="text-va-text">{lastDraft.description}</div>
                </div>
              {/if}
              <div>
                <div class="text-xs text-va-muted">Status</div>
                <div class="text-va-text">{lastDraft.status}</div>
              </div>
              <div class="pt-2 border-t border-va-border/50 text-xs text-va-muted">
                Open the bunq app to approve. Once approved, the payment executes and shows up in transactions on the next sync.
              </div>
              <div class="pt-2">
                <Button variant="secondary" onclick={refreshStatus}>
                  Refresh Status
                </Button>
              </div>
            </div>
          {/if}
        </Card>
      </div>
    </div>
  {/if}
</div>

<svelte:window
  onclick={(e) => {
    const t = e.target
    if (t && t.closest && !t.closest('.payments-autocomplete')) {
      showSuggestions = false
    }
  }}
/>
