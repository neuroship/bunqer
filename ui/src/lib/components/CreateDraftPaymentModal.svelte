<script>
  import Modal from './Modal.svelte'
  import Button from './Button.svelte'
  import Input from './Input.svelte'
  import api from '../api.js'

  let show = $state(false)
  let accounts = $state([])
  let loadingAccounts = $state(false)
  let submitting = $state(false)
  let error = $state('')

  let form = $state({
    account_id: '',
    amount: '',
    currency: 'EUR',
    counterparty_iban: '',
    counterparty_name: '',
    description: ''
  })

  function isValidIban(iban) {
    const cleaned = (iban || '').replace(/\s+/g, '').toUpperCase()
    return /^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$/.test(cleaned)
  }

  function formatIban(iban) {
    return (iban || '').replace(/\s+/g, '').replace(/(.{4})/g, '$1 ').trim()
  }

  let amountValid = $derived(parseFloat(form.amount) > 0)
  let ibanValid = $derived(isValidIban(form.counterparty_iban))
  let nameValid = $derived(form.counterparty_name.trim().length > 0)
  let accountValid = $derived(!!form.account_id)
  let canSubmit = $derived(amountValid && ibanValid && nameValid && accountValid && !submitting)

  export async function open(transaction) {
    error = ''
    form = {
      account_id: transaction.account_id ? String(transaction.account_id) : '',
      amount: Math.abs(parseFloat(transaction.amount) || 0).toFixed(2),
      currency: transaction.currency || 'EUR',
      counterparty_iban: transaction.counterparty_iban || '',
      counterparty_name: transaction.counterparty_name || '',
      description: (transaction.description || '').slice(0, 140)
    }
    show = true
    await loadAccounts()
  }

  async function loadAccounts() {
    loadingAccounts = true
    try {
      const accs = await api.setup.listAccounts()
      accounts = accs.filter(a => a.monetary_account_id)
      const match = accounts.find(a => String(a.id) === form.account_id)
      if (!match) {
        form.account_id = accounts.length === 1 ? String(accounts[0].id) : ''
      }
    } catch (e) {
      console.error('Failed to load accounts:', e)
      error = e.message || 'Failed to load accounts'
    } finally {
      loadingAccounts = false
    }
  }

  async function submit() {
    if (!canSubmit) return
    error = ''
    submitting = true
    try {
      await api.payments.createDraft({
        account_id: Number(form.account_id),
        amount: form.amount,
        currency: form.currency,
        counterparty_iban: form.counterparty_iban.replace(/\s+/g, '').toUpperCase(),
        counterparty_name: form.counterparty_name.trim(),
        description: form.description
      })
      window.showToast?.('Draft payment created. Approve it on the Payments page or in the bunq app.', 'success')
      show = false
    } catch (e) {
      error = e.message || 'Failed to create draft payment'
      window.showToast?.(error, 'error')
    } finally {
      submitting = false
    }
  }
</script>

<Modal bind:show title="New Draft Payment" size="lg">
  <div class="mb-3">
    <label class="block text-sm text-va-muted mb-1.5">
      From account <span class="text-va-danger">*</span>
    </label>
    <select
      bind:value={form.account_id}
      disabled={loadingAccounts}
      class="select select-sm bg-va-canvas border-va-border text-va-text w-full"
    >
      <option value="">{loadingAccounts ? 'Loading accounts…' : 'Select an account'}</option>
      {#each accounts as acc}
        <option value={String(acc.id)}>
          {acc.name}{acc.iban ? ` — ${formatIban(acc.iban)}` : ''}
        </option>
      {/each}
    </select>
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

  <Input
    label="Counterparty name"
    bind:value={form.counterparty_name}
    placeholder="Recipient name"
    required
    error={form.counterparty_name && !nameValid ? 'Required' : ''}
  />

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

  {#if error}
    <div class="mt-3 p-3 rounded-lg bg-va-danger/10 border border-va-danger/30 text-sm text-va-danger">
      {error}
    </div>
  {/if}

  <div class="flex justify-end gap-3 mt-5 pt-4 border-t border-va-border">
    <Button variant="secondary" onclick={() => show = false} disabled={submitting}>
      Cancel
    </Button>
    <Button onclick={submit} loading={submitting} disabled={!canSubmit}>
      <span class="icon-[tabler--send] w-3.5 h-3.5"></span>
      Create Draft Payment
    </Button>
  </div>
</Modal>
