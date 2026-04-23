<script>
  import { onMount, onDestroy } from 'svelte'
  import Card from '../components/Card.svelte'
  import Modal from '../components/Modal.svelte'
  import api from '../api.js'
  import { getPrivacyMode } from '../privacy.svelte.js'

  let privacyOn = $derived(getPrivacyMode())

  let transactions = $state([])
  let loading = $state(true)
  let debounceTimer = null

  // Pagination state
  const PAGE_SIZE = 50
  let totalCount = $state(0)
  let hasMore = $state(false)
  let loadingMore = $state(false)
  let observer = null
  let sentinelEl = $state(null)

  // Filter options from API
  let filterOptions = $state({ accounts: [], categories: [] })

  // Filter state
  const FILTERS_STORAGE_KEY = 'transactions-filters'
  const defaultFilters = {
    query: '',
    account_id: '',
    category_id: '',
    direction: '',
    start_date: '',
    end_date: '',
    min_amount: '',
    max_amount: '',
    has_document: ''
  }
  let filters = $state(loadFilters())

  function loadFilters() {
    try {
      const stored = localStorage.getItem(FILTERS_STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        return { ...defaultFilters, ...parsed }
      }
    } catch (e) {
      console.error('Failed to load filter preferences:', e)
    }
    return { ...defaultFilters }
  }

  function saveFilters() {
    try {
      localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(filters))
    } catch (e) {
      console.error('Failed to save filter preferences:', e)
    }
  }

  // Collapsed filter sections - auto-open if filters are active from localStorage
  let showFilters = $state(
    filters.account_id || filters.category_id || filters.direction || filters.start_date || filters.end_date ||
    filters.min_amount || filters.max_amount || filters.has_document
  )

  // Sorting state
  let sortBy = $state('')
  let sortOrder = $state('')

  // Account balances: always visible, masked by global privacy toggle
  let showBalances = true

  // Raw JSON modal state
  let showRawModal = $state(false)
  let rawJson = $state(null)
  let rawJsonLoading = $state(false)

  // Inline editing state
  let editingTransactionId = $state(null)
  let editingField = $state(null) // 'category' or 'tag'
  let editingTagValue = $state('')
  let savingTransaction = $state(null)

  // Apply rules state
  let applyingRules = $state(false)

  // Sync state
  let syncing = $state(false)

  // Create rule modal state
  let showCreateRuleModal = $state(false)
  let savingRule = $state(false)
  let ruleTargetCategoryId = $state('')
  let ruleMode = $state('create') // 'create' or 'existing'
  let existingRules = $state([])
  let loadingExistingRules = $state(false)
  let selectedExistingRuleId = $state('')
  let newConditions = $state([]) // conditions to append in 'existing' mode
  let ruleForm = $state({
    name: '',
    match: 'all',
    conditions: [{ field: 'description', operator: 'contains', value: '' }],
    is_active: true,
    priority: 0
  })

  const fieldOptions = [
    { value: 'description', label: 'Description' },
    { value: 'counterparty_name', label: 'Counterparty Name' },
    { value: 'counterparty_iban', label: 'Counterparty IBAN' },
    { value: 'account_name', label: 'Account Name' },
    { value: 'amount', label: 'Amount' },
    { value: 'direction', label: 'Direction' },
    { value: 'type', label: 'Type' },
    { value: 'sub_type', label: 'Sub Type' }
  ]

  const operatorOptions = {
    description: [
      { value: 'contains', label: 'contains' },
      { value: 'not_contains', label: 'does not contain' },
      { value: 'equals', label: 'equals' },
      { value: 'starts_with', label: 'starts with' },
      { value: 'ends_with', label: 'ends with' }
    ],
    counterparty_name: [
      { value: 'contains', label: 'contains' },
      { value: 'equals', label: 'equals' },
      { value: 'starts_with', label: 'starts with' }
    ],
    counterparty_iban: [
      { value: 'equals', label: 'equals' },
      { value: 'starts_with', label: 'starts with' }
    ],
    account_name: [
      { value: 'equals', label: 'equals' },
      { value: 'contains', label: 'contains' }
    ],
    amount: [
      { value: 'equals', label: 'equals' },
      { value: 'greater_than', label: 'greater than' },
      { value: 'less_than', label: 'less than' }
    ],
    direction: [
      { value: 'equals', label: 'is' }
    ],
    type: [
      { value: 'equals', label: 'equals' }
    ],
    sub_type: [
      { value: 'equals', label: 'equals' }
    ]
  }

  // Column configuration
  const STORAGE_KEY = 'transactions-visible-columns'
  const allColumns = [
    { id: 'date', label: 'Date', align: 'left' },
    { id: 'account', label: 'Account', align: 'left' },
    { id: 'counterparty', label: 'Counterparty', align: 'left' },
    { id: 'description', label: 'Description', align: 'left' },
    { id: 'type', label: 'Type', align: 'left' },
    { id: 'amount', label: 'Amount', align: 'right' },
    { id: 'balance_after', label: 'Balance After', align: 'right' },
    { id: 'location', label: 'Location', align: 'left' },
    { id: 'document', label: 'Document', align: 'left' },
    { id: 'category', label: 'Category', align: 'left' },
    { id: 'tag', label: 'Tag', align: 'left' }
  ]
  const defaultVisibleColumns = ['date', 'account', 'counterparty', 'description', 'type', 'amount']
  
  let visibleColumns = $state(loadVisibleColumns())
  let showColumnSettings = $state(false)

  function loadVisibleColumns() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        // Validate that stored columns still exist
        return parsed.filter(id => allColumns.some(col => col.id === id))
      }
    } catch (e) {
      console.error('Failed to load column preferences:', e)
    }
    return [...defaultVisibleColumns]
  }

  function saveVisibleColumns() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(visibleColumns))
    } catch (e) {
      console.error('Failed to save column preferences:', e)
    }
  }

  function toggleColumn(columnId) {
    if (visibleColumns.includes(columnId)) {
      // Don't allow hiding all columns
      if (visibleColumns.length > 1) {
        visibleColumns = visibleColumns.filter(id => id !== columnId)
      }
    } else {
      visibleColumns = [...visibleColumns, columnId]
    }
    saveVisibleColumns()
  }

  function isColumnVisible(columnId) {
    return visibleColumns.includes(columnId)
  }

  function handleTransactionsUpdated() {
    console.log('Transactions updated, refreshing list...')
    loadTransactions()
  }

  function handleClickOutside(event) {
    const dropdown = document.querySelector('[data-column-settings]')
    if (dropdown && !dropdown.contains(event.target)) {
      showColumnSettings = false
    }
  }

  onMount(async () => {
    await Promise.all([loadFilterOptions(), loadTransactions()])
    window.addEventListener('transactions-updated', handleTransactionsUpdated)
    document.addEventListener('click', handleClickOutside)

    // Setup IntersectionObserver for infinite scroll
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading && !loadingMore) {
          loadMore()
        }
      },
      { rootMargin: '100px' }
    )
  })

  onDestroy(() => {
    window.removeEventListener('transactions-updated', handleTransactionsUpdated)
    document.removeEventListener('click', handleClickOutside)
    if (observer) observer.disconnect()
  })

  // Observe sentinel element when it changes
  $effect(() => {
    if (sentinelEl && observer) {
      const el = sentinelEl
      observer.observe(el)
      return () => observer.unobserve(el)
    }
  })

  async function loadFilterOptions() {
    try {
      filterOptions = await api.transactions.filters()
    } catch (error) {
      console.error('Failed to load filter options:', error)
    }
  }

  async function loadTransactions() {
    loading = true
    try {
      const params = { ...filters, limit: PAGE_SIZE, offset: 0 }
      if (sortBy) params.sort_by = sortBy
      if (sortOrder) params.sort_order = sortOrder
      const response = await api.transactions.list(params)
      transactions = response.items
      totalCount = response.total
      hasMore = transactions.length < totalCount
    } catch (error) {
      console.error('Failed to load transactions:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      loading = false
    }
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return
    loadingMore = true
    try {
      const params = { ...filters, limit: PAGE_SIZE, offset: transactions.length }
      if (sortBy) params.sort_by = sortBy
      if (sortOrder) params.sort_order = sortOrder
      const response = await api.transactions.list(params)
      transactions = [...transactions, ...response.items]
      hasMore = transactions.length < response.total
    } catch (error) {
      console.error('Failed to load more transactions:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      loadingMore = false
    }
  }

  async function viewRawJson(transactionId) {
    rawJsonLoading = true
    rawJson = null
    showRawModal = true
    try {
      rawJson = await api.transactions.getRaw(transactionId)
    } catch (error) {
      window.showToast?.(error.message, 'error')
      showRawModal = false
    } finally {
      rawJsonLoading = false
    }
  }

  function closeRawModal() {
    showRawModal = false
    rawJson = null
  }

  function handleFilterChange() {
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      saveFilters()
      loadTransactions()
    }, 300)
  }

  function handleFilterSelect() {
    saveFilters()
    loadTransactions()
  }

  function clearFilters() {
    filters = { ...defaultFilters }
    saveFilters()
    loadTransactions()
  }

  function toggleSort(column) {
    if (sortBy === column) {
      if (sortOrder === 'desc') {
        sortOrder = 'asc'
      } else if (sortOrder === 'asc') {
        // Third click: clear sort
        sortBy = ''
        sortOrder = ''
      }
    } else {
      sortBy = column
      sortOrder = 'desc'
    }
    loadTransactions()
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

  function getAccountName(accountId) {
    const account = filterOptions.accounts.find(a => a.id === accountId)
    return account?.name || `Account ${accountId}`
  }

  function getCategoryName(categoryId) {
    if (!categoryId) return null
    const category = filterOptions.categories?.find(c => c.id === categoryId)
    return category?.name || null
  }

  function getCategoryColor(categoryId) {
    if (!categoryId) return null
    const category = filterOptions.categories?.find(c => c.id === categoryId)
    return category?.color || null
  }

  function getMapUrl(lat, lng) {
    return `https://www.google.com/maps?q=${lat},${lng}`
  }

  function hasLocation(transaction) {
    return transaction.geo_latitude != null && transaction.geo_longitude != null
  }

  // Inline editing functions
  function startEditingCategory(transaction) {
    editingTransactionId = transaction.id
    editingField = 'category'
  }

  function startEditingTag(transaction) {
    editingTransactionId = transaction.id
    editingField = 'tag'
    editingTagValue = transaction.tag || ''
  }

  function cancelEditing() {
    editingTransactionId = null
    editingField = null
    editingTagValue = ''
  }

  async function saveCategory(transactionId, categoryId) {
    savingTransaction = transactionId
    try {
      const updated = await api.transactions.update(transactionId, { category_id: categoryId })
      // Update local state
      transactions = transactions.map(t => t.id === transactionId ? { ...t, category_id: updated.category_id } : t)
      cancelEditing()
    } catch (error) {
      console.error('Failed to update category:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      savingTransaction = null
    }
  }

  async function saveTag(transactionId) {
    savingTransaction = transactionId
    try {
      const tag = editingTagValue.trim() || null
      const updated = await api.transactions.update(transactionId, { tag })
      // Update local state
      transactions = transactions.map(t => t.id === transactionId ? { ...t, tag: updated.tag } : t)
      cancelEditing()
    } catch (error) {
      console.error('Failed to update tag:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      savingTransaction = null
    }
  }

  function handleTagKeydown(event, transactionId) {
    if (event.key === 'Enter') {
      saveTag(transactionId)
    } else if (event.key === 'Escape') {
      cancelEditing()
    }
  }

  async function applyRules() {
    applyingRules = true
    try {
      const result = await api.transactions.applyRules()
      if (result.categorized > 0) {
        window.showToast?.(result.message, 'success')
        // Reload transactions to show updated categories
        await loadTransactions()
      } else {
        window.showToast?.(result.message, 'info')
      }
    } catch (error) {
      console.error('Failed to apply rules:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      applyingRules = false
    }
  }

  async function syncTransactions() {
    syncing = true
    try {
      await api.setup.syncNow()
      window.showToast?.('Sync started', 'info')
    } catch (error) {
      console.error('Failed to sync transactions:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      syncing = false
    }
  }

  // Create rule functions
  function openCreateRuleModal(transaction) {
    const conditions = []
    if (transaction.counterparty_name) {
      conditions.push({ field: 'counterparty_name', operator: 'contains', value: transaction.counterparty_name })
    }
    if (transaction.description) {
      conditions.push({ field: 'description', operator: 'contains', value: transaction.description })
    }
    if (conditions.length === 0) {
      conditions.push({ field: 'description', operator: 'contains', value: '' })
    }

    const ruleName = transaction.counterparty_name
      ? `Rule for ${transaction.counterparty_name}`
      : transaction.description
        ? `Rule for ${transaction.description.slice(0, 50)}`
        : 'New Rule'

    ruleForm = {
      name: ruleName,
      match: 'all',
      conditions,
      is_active: true,
      priority: 0
    }
    newConditions = conditions.map(c => ({ ...c }))
    ruleMode = 'create'
    existingRules = []
    selectedExistingRuleId = ''
    ruleTargetCategoryId = transaction.category_id ? String(transaction.category_id) : ''
    showCreateRuleModal = true
    if (ruleTargetCategoryId) {
      loadExistingRules(ruleTargetCategoryId)
    }
  }

  async function loadExistingRules(categoryId) {
    if (!categoryId) {
      existingRules = []
      return
    }
    loadingExistingRules = true
    try {
      existingRules = await api.categories.rules.list(parseInt(categoryId))
    } catch (error) {
      existingRules = []
    } finally {
      loadingExistingRules = false
    }
  }

  function handleRuleCategoryChange(categoryId) {
    ruleTargetCategoryId = categoryId
    selectedExistingRuleId = ''
    loadExistingRules(categoryId)
  }

  function addRuleCondition() {
    ruleForm.conditions = [...ruleForm.conditions, { field: 'description', operator: 'contains', value: '' }]
  }

  function removeRuleCondition(index) {
    if (ruleForm.conditions.length > 1) {
      ruleForm.conditions = ruleForm.conditions.filter((_, i) => i !== index)
    }
  }

  function updateRuleConditionField(index, field) {
    const operators = operatorOptions[field]
    ruleForm.conditions[index].field = field
    ruleForm.conditions[index].operator = operators[0].value
    ruleForm.conditions[index].value = ''
  }

  async function saveRule() {
    if (ruleMode === 'create') {
      if (!ruleTargetCategoryId) {
        window.showToast?.('Please select a category', 'error')
        return
      }
      if (!ruleForm.name.trim()) {
        window.showToast?.('Rule name is required', 'error')
        return
      }
      const hasEmptyValue = ruleForm.conditions.some(c => !c.value && c.value !== 0)
      if (hasEmptyValue) {
        window.showToast?.('All conditions must have a value', 'error')
        return
      }

      savingRule = true
      try {
        await api.categories.rules.create(parseInt(ruleTargetCategoryId), {
          name: ruleForm.name.trim(),
          conditions: {
            match: ruleForm.match,
            rules: ruleForm.conditions
          },
          is_active: ruleForm.is_active,
          priority: ruleForm.priority
        })
        showCreateRuleModal = false
        window.showToast?.('Rule created successfully', 'success')
      } catch (error) {
        window.showToast?.(error.message, 'error')
      } finally {
        savingRule = false
      }
    } else {
      // Add to existing rule
      if (!selectedExistingRuleId) {
        window.showToast?.('Please select a rule', 'error')
        return
      }
      const hasEmptyValue = newConditions.some(c => !c.value && c.value !== 0)
      if (hasEmptyValue) {
        window.showToast?.('All conditions must have a value', 'error')
        return
      }

      const rule = existingRules.find(r => r.id === parseInt(selectedExistingRuleId))
      if (!rule) return

      savingRule = true
      try {
        const mergedConditions = [...rule.conditions.rules, ...newConditions]
        await api.categories.rules.update(rule.id, {
          conditions: {
            match: rule.conditions.match,
            rules: mergedConditions
          }
        })
        showCreateRuleModal = false
        window.showToast?.(`Conditions added to "${rule.name}"`, 'success')
      } catch (error) {
        window.showToast?.(error.message, 'error')
      } finally {
        savingRule = false
      }
    }
  }

  // Check if any filters are active
  let hasActiveFilters = $derived(
    filters.account_id || filters.category_id || filters.direction || filters.start_date || filters.end_date ||
    filters.min_amount || filters.max_amount || filters.has_document
  )

  $effect(() => {
    filters.query
    handleFilterChange()
  })
</script>

<div>
  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
    <h1 class="text-lg font-semibold text-va-text">Transactions</h1>
    <div class="flex items-center gap-2 sm:gap-3 flex-wrap">
      {#if hasActiveFilters}
        <button onclick={clearFilters} class="text-sm text-va-muted hover:text-va-text transition-colors">
          Clear filters
        </button>
      {/if}
      <button
        onclick={syncTransactions}
        disabled={syncing}
        class="p-2 rounded-lg border-2 transition-all bg-va-subtle border-va-border text-va-muted hover:text-va-text hover:border-va-muted disabled:opacity-50 disabled:cursor-not-allowed"
        title="Fetch new transactions"
      >
        {#if syncing}
          <div class="w-4 h-4 border-2 border-va-muted border-t-transparent rounded-full animate-spin"></div>
        {:else}
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        {/if}
      </button>
      <button 
        onclick={applyRules}
        disabled={applyingRules}
        class="text-sm px-4 py-2 rounded-lg border-2 transition-all font-medium bg-va-subtle border-va-border text-va-muted hover:text-va-text hover:border-va-muted disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        title="Apply categorization rules to uncategorized transactions"
      >
        {#if applyingRules}
          <div class="w-3 h-3 border-2 border-va-muted border-t-transparent rounded-full animate-spin"></div>
        {:else}
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
          </svg>
        {/if}
        Apply Rules
      </button>
      <button 
        onclick={() => showFilters = !showFilters}
        class="text-sm px-4 py-2 rounded-lg border-2 transition-all font-medium {showFilters ? 'bg-va-accent/15 border-va-accent text-va-accent' : 'bg-va-subtle border-va-border text-va-muted hover:text-va-text hover:border-va-muted'}"
      >
        Filters {hasActiveFilters ? '•' : ''}
      </button>
      <!-- Column Settings -->
      <div class="relative" data-column-settings>
        <button 
          onclick={() => showColumnSettings = !showColumnSettings}
          class="text-sm px-4 py-2 rounded-lg border-2 transition-all font-medium {showColumnSettings ? 'bg-va-accent/15 border-va-accent text-va-accent' : 'bg-va-subtle border-va-border text-va-muted hover:text-va-text hover:border-va-muted'}"
          title="Configure columns"
        >
          <svg class="w-4 h-4 inline-block" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
          </svg>
        </button>
        {#if showColumnSettings}
          <div class="absolute right-0 top-full mt-2 w-48 bg-va-card border border-va-border rounded-lg shadow-lg z-10">
            <div class="p-2">
              <div class="text-xs text-va-muted font-medium px-2 py-1 mb-1">Show columns</div>
              {#each allColumns as column}
                <label class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-va-hover cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isColumnVisible(column.id)}
                    onchange={() => toggleColumn(column.id)}
                    disabled={visibleColumns.length === 1 && isColumnVisible(column.id)}
                    class="rounded border-va-border text-va-accent focus:ring-va-accent"
                  />
                  <span class="text-sm text-va-text">{column.label}</span>
                </label>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </div>
  </div>

  <!-- Account Balances -->
  {#if showBalances && filterOptions.accounts.length > 0}
    <div class="flex gap-3 mb-4 flex-wrap">
      {#each filterOptions.accounts as account}
        <div class="flex items-center gap-2 px-3 py-2 bg-va-subtle border border-va-border rounded-lg">
          <span class="text-xs text-va-muted" class:privacy-blur={privacyOn}>{account.name}</span>
          <span class="text-sm font-medium {account.balance && parseFloat(account.balance) >= 0 ? 'text-va-success' : 'text-va-danger'}" class:privacy-blur={privacyOn}>
            {account.balance != null ? formatCurrency(parseFloat(account.balance)) : '-'}
          </span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Search & Filters -->
  <Card class="mb-4">
    <div class="space-y-3">
      <!-- Search -->
      <input
        type="text"
        placeholder="Search description, counterparty..."
        bind:value={filters.query}
        class="input input-sm bg-va-canvas border-va-border text-va-text"
      />

      <!-- Collapsible Filters -->
      {#if showFilters}
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-3 border-t border-va-border">
          <!-- Account -->
          <div>
            <label class="block text-xs text-va-muted mb-1">Account</label>
            <select bind:value={filters.account_id} onchange={handleFilterSelect} class="input input-sm bg-va-canvas border-va-border text-va-text">
              <option value="">All accounts</option>
              {#each filterOptions.accounts as account}
                <option value={account.id}>{account.name}</option>
              {/each}
            </select>
          </div>

          <!-- Category -->
          <div>
            <label class="block text-xs text-va-muted mb-1">Category</label>
            <select bind:value={filters.category_id} onchange={handleFilterSelect} class="input input-sm bg-va-canvas border-va-border text-va-text">
              <option value="">All categories</option>
              <option value="none">Uncategorized</option>
              {#each filterOptions.categories || [] as category}
                <option value={category.id}>{category.name}</option>
              {/each}
            </select>
          </div>

          <!-- Direction -->
          <div>
            <label class="block text-xs text-va-muted mb-1">Direction</label>
            <select bind:value={filters.direction} onchange={handleFilterSelect} class="input input-sm bg-va-canvas border-va-border text-va-text">
              <option value="">All</option>
              <option value="in">Income</option>
              <option value="out">Expense</option>
            </select>
          </div>

          <!-- Document Match -->
          <div>
            <label class="block text-xs text-va-muted mb-1">Document</label>
            <select bind:value={filters.has_document} onchange={handleFilterSelect} class="input input-sm bg-va-canvas border-va-border text-va-text">
              <option value="">All</option>
              <option value="yes">Has document</option>
              <option value="no">No document</option>
            </select>
          </div>

          <!-- Date Range -->
          <div>
            <label class="block text-xs text-va-muted mb-1">From Date</label>
            <input 
              type="date" 
              bind:value={filters.start_date} 
              onchange={handleFilterSelect}
              class="input input-sm bg-va-canvas border-va-border text-va-text"
            />
          </div>

          <div>
            <label class="block text-xs text-va-muted mb-1">To Date</label>
            <input 
              type="date" 
              bind:value={filters.end_date} 
              onchange={handleFilterSelect}
              class="input input-sm bg-va-canvas border-va-border text-va-text"
            />
          </div>

          <!-- Amount Range -->
          <div>
            <label class="block text-xs text-va-muted mb-1">Min Amount</label>
            <input 
              type="number" 
              placeholder="0.00"
              bind:value={filters.min_amount} 
              onchange={handleFilterSelect}
              class="input input-sm bg-va-canvas border-va-border text-va-text"
              step="0.01"
            />
          </div>

          <div>
            <label class="block text-xs text-va-muted mb-1">Max Amount</label>
            <input 
              type="number" 
              placeholder="0.00"
              bind:value={filters.max_amount} 
              onchange={handleFilterSelect}
              class="input input-sm bg-va-canvas border-va-border text-va-text"
              step="0.01"
            />
          </div>
        </div>
      {/if}
    </div>
  </Card>

  <!-- Transactions List -->
  <Card>
    {#if loading}
      <div class="flex items-center justify-center h-20">
        <div class="w-5 h-5 border-2 border-va-muted border-t-transparent rounded-full animate-spin"></div>
      </div>
    {:else if transactions.length === 0}
      <div class="text-center py-6">
        <div class="text-3xl mb-2">💳</div>
        <p class="text-va-muted text-xs">No transactions found</p>
        {#if filters.query || hasActiveFilters}
          <p class="text-va-muted text-xs mt-0.5">Try adjusting your filters</p>
        {:else}
          <p class="text-va-muted text-xs mt-0.5">Connect your bank account to import transactions</p>
        {/if}
      </div>
    {:else}
      <div class="overflow-x-auto rounded-lg">
        <table class="w-full min-w-[600px]">
          <thead>
            <tr class="border-b border-va-border">
              {#each allColumns as column}
                {#if isColumnVisible(column.id)}
                  {#if column.id === 'amount'}
                    <th class="text-{column.align} py-3 px-3 text-sm text-va-muted font-medium">
                      <button
                        onclick={() => toggleSort('amount')}
                        class="inline-flex items-center gap-1 hover:text-va-text transition-colors {sortBy === 'amount' ? 'text-va-accent' : ''}"
                      >
                        {column.label}
                        {#if sortBy === 'amount'}
                          <svg class="w-3 h-3 transition-transform {sortOrder === 'asc' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                          </svg>
                        {:else}
                          <svg class="w-3 h-3 opacity-0 group-hover:opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
                          </svg>
                        {/if}
                      </button>
                    </th>
                  {:else}
                    <th class="text-{column.align} py-3 px-3 text-sm text-va-muted font-medium">{column.label}</th>
                  {/if}
                {/if}
              {/each}
              <th class="w-10"></th>
            </tr>
          </thead>
          <tbody>
            {#each transactions as transaction}
              <tr class="border-b border-va-border/30 hover:bg-va-hover/50 transition-colors">
                {#if isColumnVisible('date')}
                  <td class="py-3 px-3 text-sm text-va-muted whitespace-nowrap">
                    {formatDate(transaction.transaction_date)}
                  </td>
                {/if}
                {#if isColumnVisible('account')}
                  <td class="py-3 px-3 text-sm text-va-muted whitespace-nowrap" class:privacy-blur={privacyOn}>
                    {getAccountName(transaction.account_id)}
                  </td>
                {/if}
                {#if isColumnVisible('counterparty')}
                  <td class="py-3 px-3" class:privacy-blur={privacyOn}>
                    <div class="text-sm text-va-text">{transaction.counterparty_name || 'Unknown'}</div>
                    {#if transaction.counterparty_iban}
                      <div class="text-xs text-va-muted mt-0.5">{transaction.counterparty_iban}</div>
                    {/if}
                  </td>
                {/if}
                {#if isColumnVisible('description')}
                  <td class="py-3 px-3 text-sm text-va-muted max-w-xs truncate" title={transaction.description}>
                    {transaction.description || '-'}
                  </td>
                {/if}
                {#if isColumnVisible('type')}
                  <td class="py-3 px-3 whitespace-nowrap">
                    {#if transaction.type}
                      <span class="text-xs px-2 py-1 rounded-md bg-va-hover border border-va-border text-va-muted">
                        {transaction.type}
                      </span>
                    {/if}
                    {#if transaction.sub_type}
                      <span class="text-xs px-2 py-1 rounded-md bg-va-hover border border-va-border text-va-muted ml-1">
                        {transaction.sub_type}
                      </span>
                    {/if}
                  </td>
                {/if}
                {#if isColumnVisible('amount')}
                  <td class="py-3 px-3 text-right text-sm font-medium whitespace-nowrap {transaction.amount >= 0 ? 'text-va-success' : 'text-va-danger'}">
                    {formatCurrency(transaction.amount)}
                  </td>
                {/if}
                {#if isColumnVisible('balance_after')}
                  <td class="py-3 px-3 text-right text-sm text-va-muted whitespace-nowrap">
                    {transaction.balance_after != null ? formatCurrency(transaction.balance_after) : '-'}
                  </td>
                {/if}
                {#if isColumnVisible('location')}
                  <td class="py-3 px-3 text-sm whitespace-nowrap">
                    {#if hasLocation(transaction)}
                      <a
                        href={getMapUrl(transaction.geo_latitude, transaction.geo_longitude)}
                        target="_blank"
                        rel="noopener noreferrer"
                        class="inline-flex items-center gap-1 text-va-accent hover:text-va-accent/80 transition-colors"
                        title="View on map"
                      >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                        <span>View</span>
                      </a>
                    {:else}
                      <span class="text-va-muted">-</span>
                    {/if}
                  </td>
                {/if}
                {#if isColumnVisible('document')}
                  <td class="py-3 px-3 whitespace-nowrap">
                    {#if transaction.document_filename}
                      <span class="text-xs px-2 py-1 rounded-md bg-va-accent/10 border border-va-accent/30 text-va-accent inline-flex items-center gap-1" title={transaction.document_filename}>
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span class="max-w-[100px] truncate">{transaction.document_filename}</span>
                      </span>
                    {:else}
                      <span class="text-sm text-va-muted/30">—</span>
                    {/if}
                  </td>
                {/if}
                {#if isColumnVisible('category')}
                  <td class="py-3 px-3 whitespace-nowrap">
                    {#if editingTransactionId === transaction.id && editingField === 'category'}
                      <!-- Category dropdown -->
                      <select
                        class="text-xs px-2 py-1 rounded-md border border-va-accent bg-va-canvas text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                        value={transaction.category_id || ''}
                        onchange={(e) => saveCategory(transaction.id, e.target.value ? parseInt(e.target.value) : null)}
                        onblur={cancelEditing}
                        disabled={savingTransaction === transaction.id}
                      >
                        <option value="">-- Remove category --</option>
                        {#each filterOptions.categories || [] as category}
                          <option value={category.id}>{category.name}</option>
                        {/each}
                      </select>
                    {:else}
                      <!-- Category display (clickable) -->
                      <button
                        onclick={() => startEditingCategory(transaction)}
                        class="text-left hover:bg-va-hover/50 rounded px-1 -mx-1 transition-colors min-w-[60px]"
                        title="Click to edit category"
                      >
                        {#if getCategoryName(transaction.category_id)}
                          <span 
                            class="text-xs px-2 py-1 rounded-md border inline-block"
                            style={getCategoryColor(transaction.category_id) ? `background-color: ${getCategoryColor(transaction.category_id)}20; border-color: ${getCategoryColor(transaction.category_id)}40; color: ${getCategoryColor(transaction.category_id)}` : ''}
                            class:bg-va-hover={!getCategoryColor(transaction.category_id)}
                            class:border-va-border={!getCategoryColor(transaction.category_id)}
                            class:text-va-muted={!getCategoryColor(transaction.category_id)}
                          >
                            {getCategoryName(transaction.category_id)}
                          </span>
                        {:else}
                          <span class="text-sm text-va-muted/50 hover:text-va-muted">+ Add</span>
                        {/if}
                      </button>
                    {/if}
                  </td>
                {/if}
                {#if isColumnVisible('tag')}
                  <td class="py-3 px-3 whitespace-nowrap">
                    {#if editingTransactionId === transaction.id && editingField === 'tag'}
                      <!-- Tag input -->
                      <input
                        type="text"
                        class="text-xs px-2 py-1 rounded-md border border-va-accent bg-va-canvas text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent w-24"
                        bind:value={editingTagValue}
                        onblur={() => saveTag(transaction.id)}
                        onkeydown={(e) => handleTagKeydown(e, transaction.id)}
                        disabled={savingTransaction === transaction.id}
                        placeholder="Enter tag..."
                      />
                    {:else}
                      <!-- Tag display (clickable) -->
                      <button
                        onclick={() => startEditingTag(transaction)}
                        class="text-left hover:bg-va-hover/50 rounded px-1 -mx-1 transition-colors min-w-[60px]"
                        title="Click to edit tag"
                      >
                        {#if transaction.tag}
                          <span class="text-xs px-2 py-1 rounded-md bg-va-accent/10 border border-va-accent/30 text-va-accent inline-block">
                            {transaction.tag}
                          </span>
                        {:else}
                          <span class="text-sm text-va-muted/50 hover:text-va-muted">+ Add</span>
                        {/if}
                      </button>
                    {/if}
                  </td>
                {/if}
                <td class="py-3 px-2">
                  <div class="flex items-center gap-0.5">
                    <button
                      onclick={() => openCreateRuleModal(transaction)}
                      class="p-1.5 text-va-muted hover:text-va-accent hover:bg-va-hover rounded-md transition-all"
                      title="Create rule from this transaction"
                    >
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                      </svg>
                    </button>
                    <button
                      onclick={() => viewRawJson(transaction.id)}
                      class="p-1.5 text-va-muted hover:text-va-accent hover:bg-va-hover rounded-md transition-all"
                      title="View raw JSON"
                    >
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                      </svg>
                    </button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <!-- Infinite scroll sentinel and footer -->
      <div class="border-t border-va-border">
        {#if hasMore}
          <div bind:this={sentinelEl} class="flex items-center justify-center py-4">
            {#if loadingMore}
              <div class="flex items-center gap-2">
                <div class="w-4 h-4 border-2 border-va-muted border-t-transparent rounded-full animate-spin"></div>
                <span class="text-sm text-va-muted">Loading more...</span>
              </div>
            {:else}
              <span class="text-sm text-va-muted">Scroll for more</span>
            {/if}
          </div>
        {/if}
        <div class="text-sm text-va-muted px-3 py-3 {hasMore ? 'border-t border-va-border' : ''}">
          Showing {transactions.length} of {totalCount} transactions
        </div>
      </div>
    {/if}
  </Card>
</div>

<!-- Raw JSON Modal -->
<Modal bind:show={showRawModal} title="Raw bunq JSON" onClose={closeRawModal}>
  <div class="max-h-96 overflow-auto rounded-lg">
    {#if rawJsonLoading}
      <div class="flex items-center justify-center py-8">
        <div class="w-5 h-5 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    {:else if rawJson}
      <pre class="text-xs text-va-text bg-va-canvas p-4 rounded-lg border border-va-border overflow-x-auto whitespace-pre-wrap">{JSON.stringify(rawJson, null, 2)}</pre>
    {:else}
      <p class="text-sm text-va-muted text-center py-4">No raw JSON available</p>
    {/if}
  </div>
</Modal>

<!-- Create Rule Modal -->
<Modal bind:show={showCreateRuleModal} title={ruleMode === 'create' ? 'Create Rule' : 'Add to Existing Rule'} size="xl">
  <div class="space-y-4">
    <!-- Mode toggle -->
    <div class="flex rounded-lg border border-va-border overflow-hidden">
      <button
        onclick={() => ruleMode = 'create'}
        class="flex-1 px-4 py-2 text-sm font-medium transition-all {ruleMode === 'create' ? 'bg-va-accent text-white' : 'bg-va-subtle text-va-muted hover:text-va-text'}"
      >
        Create New Rule
      </button>
      <button
        onclick={() => ruleMode = 'existing'}
        class="flex-1 px-4 py-2 text-sm font-medium transition-all {ruleMode === 'existing' ? 'bg-va-accent text-white' : 'bg-va-subtle text-va-muted hover:text-va-text'}"
      >
        Add to Existing Rule
      </button>
    </div>

    <!-- Category selector -->
    <div>
      <span class="block text-sm text-va-muted mb-1">Category <span class="text-va-danger">*</span></span>
      <select
        value={ruleTargetCategoryId}
        onchange={(e) => handleRuleCategoryChange(e.target.value)}
        class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
      >
        <option value="">Select a category...</option>
        {#each filterOptions.categories || [] as category}
          <option value={String(category.id)}>{category.name}</option>
        {/each}
      </select>
    </div>

    {#if ruleMode === 'existing'}
      <!-- Existing rule selector -->
      <div>
        <span class="block text-sm text-va-muted mb-1">Rule <span class="text-va-danger">*</span></span>
        {#if loadingExistingRules}
          <div class="flex items-center gap-2 py-2">
            <div class="w-4 h-4 border-2 border-va-muted border-t-transparent rounded-full animate-spin"></div>
            <span class="text-sm text-va-muted">Loading rules...</span>
          </div>
        {:else if !ruleTargetCategoryId}
          <p class="text-sm text-va-muted py-2">Select a category first</p>
        {:else if existingRules.length === 0}
          <p class="text-sm text-va-muted py-2">No existing rules for this category. Switch to "Create New Rule" instead.</p>
        {:else}
          <select
            bind:value={selectedExistingRuleId}
            class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
          >
            <option value="">Select a rule...</option>
            {#each existingRules as rule}
              <option value={String(rule.id)}>{rule.name}</option>
            {/each}
          </select>
        {/if}
      </div>

      <!-- Show selected rule's current conditions -->
      {#if selectedExistingRuleId}
        {@const selectedRule = existingRules.find(r => r.id === parseInt(selectedExistingRuleId))}
        {#if selectedRule}
          <div class="p-3 bg-va-hover/50 rounded-md border border-va-border/30">
            <span class="block text-xs text-va-muted mb-1">Current conditions (match {selectedRule.conditions.match === 'all' ? 'ALL' : 'ANY'}):</span>
            {#each selectedRule.conditions.rules as condition}
              <div class="text-xs text-va-muted">
                - {fieldOptions.find(f => f.value === condition.field)?.label || condition.field}
                <span class="text-va-text">{operatorOptions[condition.field]?.find(o => o.value === condition.operator)?.label || condition.operator}</span>
                "<span class="text-va-accent">{condition.value}</span>"
              </div>
            {/each}
          </div>
        {/if}
      {/if}

      <!-- Conditions to add -->
      <div>
        <span class="block text-sm text-va-muted mb-2">Conditions to Add</span>
        <div class="space-y-2">
          {#each newConditions as condition, index}
            <div class="flex flex-wrap items-center gap-2 p-3 bg-va-hover/50 rounded-md border border-va-accent/30">
              <select
                value={condition.field}
                onchange={(e) => {
                  const field = e.target.value
                  const operators = operatorOptions[field]
                  newConditions[index].field = field
                  newConditions[index].operator = operators[0].value
                  newConditions[index].value = ''
                }}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each fieldOptions as field}
                  <option value={field.value}>{field.label}</option>
                {/each}
              </select>

              <select
                bind:value={condition.operator}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each operatorOptions[condition.field] || [] as op}
                  <option value={op.value}>{op.label}</option>
                {/each}
              </select>

              {#if condition.field === 'direction'}
                <select
                  bind:value={condition.value}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                >
                  <option value="">Select...</option>
                  <option value="in">Income (positive)</option>
                  <option value="out">Expense (negative)</option>
                </select>
              {:else}
                <input
                  type={condition.field === 'amount' ? 'number' : 'text'}
                  bind:value={condition.value}
                  placeholder={condition.field === 'amount' ? '0.00' : 'Value...'}
                  step={condition.field === 'amount' ? '0.01' : undefined}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                />
              {/if}

              <button
                onclick={() => {
                  if (newConditions.length > 1) {
                    newConditions = newConditions.filter((_, i) => i !== index)
                  }
                }}
                disabled={newConditions.length <= 1}
                class="p-1.5 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                title="Remove condition"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          {/each}
        </div>

        <button
          onclick={() => newConditions = [...newConditions, { field: 'description', operator: 'contains', value: '' }]}
          class="mt-2 text-sm text-va-accent hover:text-va-accent/80"
        >
          + Add Condition
        </button>
      </div>
    {:else}
      <!-- Create new rule form -->
      <!-- Rule name -->
      <div>
        <span class="block text-sm text-va-muted mb-1">Rule Name <span class="text-va-danger">*</span></span>
        <input
          type="text"
          bind:value={ruleForm.name}
          placeholder="e.g. Salary from Company X"
          class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
        />
      </div>

      <!-- Match type -->
      <div>
        <span class="block text-sm text-va-muted mb-1">Match Conditions</span>
        <select
          bind:value={ruleForm.match}
          class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
        >
          <option value="all">ALL conditions must match (AND)</option>
          <option value="any">ANY condition can match (OR)</option>
        </select>
      </div>

      <!-- Conditions -->
      <div>
        <span class="block text-sm text-va-muted mb-2">Conditions</span>
        <div class="space-y-2">
          {#each ruleForm.conditions as condition, index}
            <div class="flex flex-wrap items-center gap-2 p-3 bg-va-hover/50 rounded-md border border-va-border/30">
              <select
                value={condition.field}
                onchange={(e) => updateRuleConditionField(index, e.target.value)}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each fieldOptions as field}
                  <option value={field.value}>{field.label}</option>
                {/each}
              </select>

              <select
                bind:value={condition.operator}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each operatorOptions[condition.field] || [] as op}
                  <option value={op.value}>{op.label}</option>
                {/each}
              </select>

              {#if condition.field === 'direction'}
                <select
                  bind:value={condition.value}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                >
                  <option value="">Select...</option>
                  <option value="in">Income (positive)</option>
                  <option value="out">Expense (negative)</option>
                </select>
              {:else}
                <input
                  type={condition.field === 'amount' ? 'number' : 'text'}
                  bind:value={condition.value}
                  placeholder={condition.field === 'amount' ? '0.00' : 'Value...'}
                  step={condition.field === 'amount' ? '0.01' : undefined}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                />
              {/if}

              <button
                onclick={() => removeRuleCondition(index)}
                disabled={ruleForm.conditions.length <= 1}
                class="p-1.5 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                title="Remove condition"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          {/each}
        </div>

        <button
          onclick={addRuleCondition}
          class="mt-2 text-sm text-va-accent hover:text-va-accent/80"
        >
          + Add Condition
        </button>
      </div>

      <!-- Active & Priority -->
      <div class="flex items-center gap-4">
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            bind:checked={ruleForm.is_active}
            class="rounded border-va-border text-va-accent focus:ring-va-accent"
          />
          <span class="text-sm text-va-text">Active</span>
        </label>

        <div class="flex items-center gap-2">
          <span class="text-sm text-va-muted">Priority:</span>
          <input
            type="number"
            bind:value={ruleForm.priority}
            min="0"
            class="w-16 px-2 py-1 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
          />
          <span class="text-xs text-va-muted">(lower = higher priority)</span>
        </div>
      </div>
    {/if}

    <!-- Actions -->
    <div class="flex gap-3 pt-4 border-t border-va-border">
      <button
        onclick={saveRule}
        disabled={savingRule}
        class="px-4 py-2 text-sm font-medium rounded-lg bg-va-accent text-white hover:bg-va-accent/90 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
      >
        {#if savingRule}
          <div class="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
        {/if}
        {ruleMode === 'create' ? 'Create Rule' : 'Add Conditions'}
      </button>
      <button
        onclick={() => showCreateRuleModal = false}
        class="px-4 py-2 text-sm font-medium rounded-lg border border-va-border text-va-muted hover:text-va-text hover:bg-va-hover transition-all"
      >
        Cancel
      </button>
    </div>
  </div>
</Modal>
