<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Input from '../components/Input.svelte'
  import Button from '../components/Button.svelte'
  import api from '../api.js'

  let step = $state(1)
  let loading = $state(false)
  let integrations = $state([])
  let selectedIntegration = $state(null)
  let monetaryAccounts = $state([])
  let selectedAccounts = $state([])
  let importResults = $state(null)
  let existingAccounts = $state([])
  let deletingAccountId = $state(null)

  // Form state
  let integrationName = $state('')
  let apiKey = $state('')

  onMount(async () => {
    await Promise.all([loadIntegrations(), loadAccounts()])
  })

  async function loadIntegrations() {
    try {
      integrations = await api.integrations.list()
    } catch (error) {
      console.error('Failed to load integrations:', error)
    }
  }

  async function loadAccounts() {
    try {
      existingAccounts = await api.setup.listAccounts()
    } catch (error) {
      console.error('Failed to load accounts:', error)
    }
  }

  async function deleteAccount(account) {
    if (!confirm(`Remove "${account.name}" and all its ${account.transaction_count} transactions? This cannot be undone.`)) {
      return
    }

    deletingAccountId = account.id
    try {
      await api.setup.deleteAccount(account.id)
      existingAccounts = existingAccounts.filter(a => a.id !== account.id)
      window.showToast?.(`Removed ${account.name}`, 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      deletingAccountId = null
    }
  }

  async function createIntegration() {
    if (!integrationName || !apiKey) {
      window.showToast?.('Please fill in all fields', 'error')
      return
    }

    loading = true
    try {
      const integration = await api.integrations.create({
        name: integrationName,
        type: 'bank',
        sub_type: 'bunq',
        secret_key: apiKey
      })

      integrations = [...integrations, integration]
      selectedIntegration = integration
      integrationName = ''
      apiKey = ''
      step = 2

      window.showToast?.('Integration created successfully', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      loading = false
    }
  }

  async function verifyConnection() {
    if (!selectedIntegration) return

    loading = true
    try {
      const result = await api.setup.startBunq({
        integration_id: selectedIntegration.id,
        include_inactive: false
      })

      monetaryAccounts = result.accounts
      step = 3

      window.showToast?.(`Found ${result.accounts.length} accounts`, 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      loading = false
    }
  }

  function toggleAccount(accountId) {
    if (selectedAccounts.includes(accountId)) {
      selectedAccounts = selectedAccounts.filter(id => id !== accountId)
    } else {
      selectedAccounts = [...selectedAccounts, accountId]
    }
  }

  async function setupAccounts() {
    if (selectedAccounts.length === 0) {
      window.showToast?.('Please select at least one account', 'error')
      return
    }

    loading = true
    try {
      const result = await api.setup.setupAccounts({
        integration_id: selectedIntegration.id,
        monetary_accounts: selectedAccounts
      })

      importResults = result
      step = 4

      if (result.total_new_transactions > 0) {
        window.showToast?.(`Imported ${result.total_new_transactions} transactions!`, 'success')
      } else {
        window.showToast?.('Import complete, but no new transactions found', 'warning')
      }
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      loading = false
    }
  }

  function formatCurrency(amount, currency = 'EUR') {
    return new Intl.NumberFormat('nl-NL', {
      style: 'currency',
      currency
    }).format(amount)
  }
</script>

<div>
  <h1 class="text-lg font-semibold text-va-text mb-5">Setup</h1>

  <!-- Step indicators -->
  <div class="flex items-center mb-5">
    {#each [1, 2, 3, 4] as stepNum}
      <div class="flex items-center">
        <div class="w-8 h-8 rounded-xl flex items-center justify-center text-sm font-medium transition-all
                    {step >= stepNum ? 'bg-va-success text-va-canvas shadow-soft' : 'bg-va-subtle border border-va-border text-va-muted'}">
          {stepNum}
        </div>
        {#if stepNum < 4}
          <div class="w-10 h-0.5 rounded {step > stepNum ? 'bg-va-success' : 'bg-va-border'}"></div>
        {/if}
      </div>
    {/each}
  </div>

  <!-- Step 1: Create Integration -->
  {#if step === 1}
    <Card title="Connect Bank Account">
      <p class="text-va-muted text-sm mb-4">Enter your bunq API key to connect your bank account.</p>

      <Input
        label="Integration Name"
        placeholder="e.g., My Business Account"
        bind:value={integrationName}
        required
      />

      <Input
        label="bunq API Key"
        type="password"
        placeholder="Your bunq API key"
        bind:value={apiKey}
        required
      />

      <div class="flex gap-3 mt-5">
        <Button onclick={createIntegration} {loading}>
          Create Integration
        </Button>

        {#if integrations.length > 0}
          <Button variant="secondary" onclick={() => step = 2}>
            Use Existing
          </Button>
        {/if}
      </div>

      {#if integrations.length > 0}
        <div class="mt-5 pt-4 border-t border-va-border">
          <h3 class="text-sm text-va-muted mb-3">Existing Integrations</h3>
          <div class="space-y-2">
            {#each integrations as integration}
              <button
                onclick={() => { selectedIntegration = integration; step = 2 }}
                class="w-full p-4 rounded-lg text-left border-2 transition-all
                       {selectedIntegration?.id === integration.id 
                         ? 'bg-va-accent/15 border-va-accent' 
                         : 'bg-va-hover/30 border-va-border/50 hover:border-va-muted hover:bg-va-hover/50'}"
              >
                <div class="text-sm text-va-text font-medium">{integration.name}</div>
                <div class="text-sm text-va-muted mt-0.5">{integration.sub_type}</div>
              </button>
            {/each}
          </div>
        </div>
      {/if}
    </Card>
  {/if}

  <!-- Step 2: Verify Connection -->
  {#if step === 2}
    <Card title="Verify Connection">
      <p class="text-va-muted text-sm mb-4">
        Click verify to test the connection and fetch available accounts.
      </p>

      {#if selectedIntegration}
        <div class="p-3 bg-va-hover/50 rounded-lg border border-va-border/30 mb-4">
          <div class="text-sm text-va-text font-medium">{selectedIntegration.name}</div>
          <div class="text-sm text-va-muted">{selectedIntegration.sub_type}</div>
        </div>
      {/if}

      <div class="flex gap-2">
        <Button onclick={verifyConnection} {loading}>
          Verify Connection
        </Button>
        <Button variant="secondary" onclick={() => step = 1}>
          Back
        </Button>
      </div>
    </Card>
  {/if}

  <!-- Step 3: Select Accounts -->
  {#if step === 3}
    <Card title="Select Accounts">
      <p class="text-va-muted text-sm mb-4">
        Select the accounts you want to import transactions from.
      </p>

      <div class="space-y-2 mb-5">
        {#each monetaryAccounts as account}
          <button
            onclick={() => toggleAccount(account.id)}
            class="w-full p-4 rounded-lg text-left transition-all border-2 relative
                   {selectedAccounts.includes(account.id)
                     ? 'bg-va-success/15 border-va-success'
                     : 'bg-va-hover/30 border-va-border/50 hover:border-va-muted hover:bg-va-hover/50'}"
          >
            {#if selectedAccounts.includes(account.id)}
              <div class="absolute top-3 right-3 w-5 h-5 bg-va-success rounded-full flex items-center justify-center">
                <svg class="w-3 h-3 text-va-canvas" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
                </svg>
              </div>
            {/if}
            <div class="flex items-center justify-between pr-6">
              <div>
                <div class="text-sm text-va-text font-medium">{account.display_name}</div>
                <div class="text-sm text-va-muted mt-0.5">{account.iban || 'No IBAN'}</div>
              </div>
              <div class="text-right">
                <div class="text-sm text-va-text font-medium">{formatCurrency(account.balance, account.currency)}</div>
                <div class="text-xs text-va-muted mt-0.5">{account.status}</div>
              </div>
            </div>
          </button>
        {/each}
      </div>

      <div class="flex gap-3">
        <Button onclick={setupAccounts} {loading} disabled={selectedAccounts.length === 0}>
          {#if loading}
            Importing transactions...
          {:else}
            Import Selected ({selectedAccounts.length})
          {/if}
        </Button>
        <Button variant="secondary" onclick={() => step = 2} disabled={loading}>
          Back
        </Button>
      </div>

      {#if loading}
        <div class="mt-4 p-4 bg-va-hover/50 rounded-lg border border-va-border/30">
          <div class="flex items-center gap-3">
            <div class="w-5 h-5 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
            <span class="text-sm text-va-muted">Fetching transactions from bunq... This may take a moment.</span>
          </div>
        </div>
      {/if}
    </Card>
  {/if}

  <!-- Step 4: Complete -->
  {#if step === 4}
    <Card>
      <div class="text-center py-8">
        <div class="text-5xl mb-4">🎉</div>
        <h2 class="text-lg font-semibold text-va-text mb-2">Import Complete!</h2>

        {#if importResults}
          <p class="text-va-muted text-sm mb-4">{importResults.message}</p>

          <div class="bg-va-hover/50 rounded-lg p-4 mb-5 text-left max-w-sm mx-auto border border-va-border/30">
            <div class="text-sm text-va-muted mb-2 font-medium">Import Summary:</div>
            {#each importResults.results as result}
              <div class="flex justify-between py-2 border-b border-va-border/30 last:border-0 text-sm">
                <span class="text-va-text">{result.account_name}</span>
                {#if result.status === 'success'}
                  <span class="text-va-success font-medium">{result.new_transactions} transactions</span>
                {:else}
                  <span class="text-va-danger font-medium">Error</span>
                {/if}
              </div>
            {/each}
            <div class="flex justify-between pt-3 mt-2 border-t border-va-border font-medium text-sm">
              <span class="text-va-text">Total</span>
              <span class="text-va-success">{importResults.total_new_transactions} transactions</span>
            </div>
          </div>
        {:else}
          <p class="text-va-muted text-sm mb-5">Your accounts have been connected.</p>
        {/if}

        <div class="flex gap-3 justify-center">
          <Button onclick={() => window.location.href = '/'}>
            Go to Transactions
          </Button>
          <Button variant="secondary" onclick={() => { step = 3; importResults = null }}>
            Import More
          </Button>
        </div>
      </div>
    </Card>
  {/if}

  <!-- Existing Accounts -->
  {#if existingAccounts.length > 0}
    <div class="mt-6">
      <Card title="Connected Accounts">
        <p class="text-va-muted text-xs mb-3">Remove an account to permanently delete it and all its transactions.</p>
        <div class="space-y-2">
          {#each existingAccounts as account}
            <div class="flex items-center justify-between p-3 rounded-lg bg-va-hover/30 border border-va-border/30">
              <div>
                <div class="text-sm text-va-text font-medium">{account.name}</div>
                <div class="text-xs text-va-muted mt-0.5">
                  {account.iban || 'No IBAN'} &middot; {account.transaction_count} transactions
                </div>
              </div>
              <button
                onclick={() => deleteAccount(account)}
                disabled={deletingAccountId === account.id}
                class="p-1.5 rounded-lg text-va-muted hover:text-va-danger hover:bg-va-danger/10 transition-all disabled:opacity-50"
                title="Remove account"
              >
                {#if deletingAccountId === account.id}
                  <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                {:else}
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                {/if}
              </button>
            </div>
          {/each}
        </div>
      </Card>
    </div>
  {/if}
</div>
