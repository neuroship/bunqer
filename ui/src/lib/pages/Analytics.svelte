<script>
  import { onMount, onDestroy } from 'svelte'
  import { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend } from 'chart.js'
  import Card from '../components/Card.svelte'
  import Modal from '../components/Modal.svelte'
  import CreateRuleModal from '../components/CreateRuleModal.svelte'
  import api from '../api.js'
  import { getPrivacyMode } from '../privacy.svelte.js'

  let privacyOn = $derived(getPrivacyMode())

  // Register Chart.js components
  Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend)

  let loading = $state(true)
  let stats = $state(null)
  let filterOptions = $state({ accounts: [], categories: [] })

  // Transaction drill-down modal
  let showTransactionsModal = $state(false)
  let selectedCategory = $state(null)
  let categoryTransactions = $state([])
  let loadingTransactions = $state(false)
  let txnSort = $state({ by: null, order: 'desc' }) // by: null | 'amount'
  let editingTransactionId = $state(null)
  let savingTransaction = $state(null)
  let modalChanged = $state(false)
  let createRuleModal = $state()

  let sortedTransactions = $derived(
    txnSort.by === 'amount'
      ? [...categoryTransactions].sort((a, b) =>
          txnSort.order === 'asc' ? a.amount - b.amount : b.amount - a.amount
        )
      : categoryTransactions
  )

  // Filter state
  const FILTERS_STORAGE_KEY = 'analytics-filters'
  const defaultFilters = {
    account_id: '',
    year: 'all',
    period: 'all' // 'all', 'q1', 'q2', 'q3', 'q4', '01', '02', ... '12'
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

  // Available years (will be populated from current year going back)
  let availableYears = $state([])

  // Chart
  let chartCanvas = $state(null)
  let chartInstance = null

  // Quarter and month options
  const quarterOptions = [
    { id: 'q1', label: 'Q1 (Jan-Mar)' },
    { id: 'q2', label: 'Q2 (Apr-Jun)' },
    { id: 'q3', label: 'Q3 (Jul-Sep)' },
    { id: 'q4', label: 'Q4 (Oct-Dec)' }
  ]

  const monthOptions = [
    { id: '01', label: 'January' },
    { id: '02', label: 'February' },
    { id: '03', label: 'March' },
    { id: '04', label: 'April' },
    { id: '05', label: 'May' },
    { id: '06', label: 'June' },
    { id: '07', label: 'July' },
    { id: '08', label: 'August' },
    { id: '09', label: 'September' },
    { id: '10', label: 'October' },
    { id: '11', label: 'November' },
    { id: '12', label: 'December' }
  ]

  onMount(async () => {
    // Generate available years (current year back to 2020)
    const currentYear = new Date().getFullYear()
    availableYears = []
    for (let y = currentYear; y >= 2020; y--) {
      availableYears.push(y)
    }

    await loadFilterOptions()
    await loadStats()
    window.addEventListener('transactions-updated', loadStats)
  })

  onDestroy(() => {
    window.removeEventListener('transactions-updated', loadStats)
    if (chartInstance) {
      chartInstance.destroy()
    }
  })

  async function loadFilterOptions() {
    try {
      filterOptions = await api.transactions.filters()
    } catch (error) {
      console.error('Failed to load filter options:', error)
    }
  }

  function getDateRange() {
    let start_date = null
    let end_date = null

    if (filters.year === 'all') {
      return { start_date, end_date }
    }

    const year = parseInt(filters.year)

    if (filters.period === 'all') {
      // Full year
      start_date = `${year}-01-01`
      end_date = `${year}-12-31`
    } else if (filters.period.startsWith('q')) {
      // Quarter
      const quarter = parseInt(filters.period.substring(1)) - 1
      const quarterStart = new Date(year, quarter * 3, 1)
      const quarterEnd = new Date(year, quarter * 3 + 3, 0)
      start_date = quarterStart.toISOString().split('T')[0]
      end_date = quarterEnd.toISOString().split('T')[0]
    } else {
      // Month
      const month = filters.period
      const lastDay = new Date(year, parseInt(month), 0).getDate()
      start_date = `${year}-${month}-01`
      end_date = `${year}-${month}-${String(lastDay).padStart(2, '0')}`
    }

    return { start_date, end_date }
  }

  async function loadStats() {
    loading = true
    try {
      const { start_date, end_date } = getDateRange()
      const params = {}
      
      if (filters.account_id) {
        params.account_id = filters.account_id
      }
      if (start_date) {
        params.start_date = start_date
      }
      if (end_date) {
        params.end_date = end_date
      }

      stats = await api.transactions.stats(params)
      updateChart()
    } catch (error) {
      console.error('Failed to load stats:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      loading = false
    }
  }

  function updateChart() {
    if (!chartCanvas || !stats?.by_category) return

    // Destroy existing chart
    if (chartInstance) {
      chartInstance.destroy()
    }

    // Sort by net amount (absolute value, descending)
    const sortedCategories = [...stats.by_category].sort(
      (a, b) => Math.abs(parseFloat(b.total)) - Math.abs(parseFloat(a.total))
    )

    const labels = sortedCategories.map(c => c.category_name)
    const netData = sortedCategories.map(c => parseFloat(c.total))
    const colors = sortedCategories.map(c => {
      const val = parseFloat(c.total)
      // Green for positive (income), red for negative (expense)
      return val >= 0 ? '#22c55e' : (c.category_color || '#ef4444')
    })

    chartInstance = new Chart(chartCanvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Net Amount',
            data: netData,
            backgroundColor: colors.map(c => c + '99'),
            borderColor: colors,
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y', // Horizontal bars for better category name display
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            callbacks: {
              label: (context) => {
                const value = context.raw
                const sign = value >= 0 ? '+' : ''
                return `${sign}€${value.toLocaleString('nl-NL', { minimumFractionDigits: 2 })}`
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: '#374151' },
            ticks: {
              color: '#9ca3af',
              callback: (value) => `€${value.toLocaleString('nl-NL')}`
            }
          },
          y: {
            grid: { color: '#374151' },
            ticks: { color: '#9ca3af' }
          }
        }
      }
    })
  }

  // Re-render chart when canvas element is available
  $effect(() => {
    if (chartCanvas && stats?.by_category) {
      updateChart()
    }
  })

  function handleFilterChange() {
    saveFilters()
    loadStats()
  }

  function handleYearChange() {
    // Reset period to 'all' when year changes
    filters.period = 'all'
    saveFilters()
    loadStats()
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

  async function showCategoryTransactions(category) {
    selectedCategory = category
    showTransactionsModal = true
    loadingTransactions = true
    categoryTransactions = []
    txnSort = { by: null, order: 'desc' }
    editingTransactionId = null
    modalChanged = false

    try {
      const { start_date, end_date } = getDateRange()
      const baseParams = {
        limit: 1000
      }

      if (filters.account_id) {
        baseParams.account_id = filters.account_id
      }
      if (start_date) {
        baseParams.start_date = start_date
      }
      if (end_date) {
        baseParams.end_date = end_date
      }

      // Handle uncategorized (null category_id)
      baseParams.category_id = category.category_id === null ? 'none' : category.category_id

      // Paginate to load all transactions in this category
      const all = []
      let offset = 0
      while (true) {
        const response = await api.transactions.list({ ...baseParams, offset })
        all.push(...response.items)
        if (response.items.length === 0 || all.length >= response.total) break
        offset += response.items.length
      }
      categoryTransactions = all
    } catch (error) {
      console.error('Failed to load transactions:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      loadingTransactions = false
    }
  }

  function toggleSortAmount() {
    if (txnSort.by !== 'amount') {
      txnSort = { by: 'amount', order: 'desc' }
    } else {
      txnSort = { by: 'amount', order: txnSort.order === 'desc' ? 'asc' : 'desc' }
    }
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

  function startEditingCategory(transaction) {
    editingTransactionId = transaction.id
  }

  function cancelEditing() {
    editingTransactionId = null
  }

  async function saveCategory(transactionId, categoryId) {
    savingTransaction = transactionId
    try {
      const updated = await api.transactions.update(transactionId, { category_id: categoryId })
      categoryTransactions = categoryTransactions.map(t =>
        t.id === transactionId ? { ...t, category_id: updated.category_id } : t
      )
      modalChanged = true
      cancelEditing()
    } catch (error) {
      console.error('Failed to update category:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      savingTransaction = null
    }
  }

  function closeTransactionsModal() {
    showTransactionsModal = false
    selectedCategory = null
    categoryTransactions = []
    editingTransactionId = null
    // Refresh chart/breakdown if any category was changed inside the modal
    if (modalChanged) {
      modalChanged = false
      loadStats()
    }
  }
</script>

<div>
  <div class="flex items-center justify-between mb-4">
    <h1 class="text-lg font-semibold text-va-text">Analytics</h1>
  </div>

  <!-- Filters -->
  <Card class="mb-4">
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Account Filter -->
      <div>
        <label for="account-filter" class="block text-xs text-va-muted mb-1">Account</label>
        <select 
          id="account-filter"
          bind:value={filters.account_id} 
          onchange={handleFilterChange} 
          class="input input-sm bg-va-canvas border-va-border text-va-text"
        >
          <option value="">All Accounts</option>
          {#each filterOptions.accounts as account}
            <option value={account.id}>{account.name}</option>
          {/each}
        </select>
      </div>

      <!-- Year Filter -->
      <div>
        <label for="year-filter" class="block text-xs text-va-muted mb-1">Year</label>
        <select 
          id="year-filter"
          bind:value={filters.year} 
          onchange={handleYearChange} 
          class="input input-sm bg-va-canvas border-va-border text-va-text"
        >
          <option value="all">All Time</option>
          {#each availableYears as year}
            <option value={year}>{year}</option>
          {/each}
        </select>
      </div>

      <!-- Quarter Filter -->
      <div>
        <label for="quarter-filter" class="block text-xs text-va-muted mb-1">Quarter</label>
        <select 
          id="quarter-filter"
          bind:value={filters.period} 
          onchange={handleFilterChange} 
          class="input input-sm bg-va-canvas border-va-border text-va-text"
          disabled={filters.year === 'all'}
        >
          <option value="all">Full Year</option>
          {#each quarterOptions as option}
            <option value={option.id}>{option.label}</option>
          {/each}
        </select>
      </div>

      <!-- Month Filter -->
      <div>
        <label for="month-filter" class="block text-xs text-va-muted mb-1">Month</label>
        <select 
          id="month-filter"
          bind:value={filters.period} 
          onchange={handleFilterChange} 
          class="input input-sm bg-va-canvas border-va-border text-va-text"
          disabled={filters.year === 'all'}
        >
          <option value="all">Full Year</option>
          {#each monthOptions as option}
            <option value={option.id}>{option.label}</option>
          {/each}
        </select>
      </div>
    </div>
  </Card>

  <!-- Summary Card -->
  {#if stats}
    <Card class="mb-4">
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 divide-y sm:divide-y-0 sm:divide-x divide-va-border">
        <div class="text-center pt-3 sm:pt-0 first:pt-0">
          <p class="text-xs text-va-muted mb-1">Net In</p>
          <p class="text-2xl font-semibold text-va-success" class:privacy-blur={privacyOn}>
            {formatCurrency(parseFloat(stats.total_income))}
          </p>
        </div>
        <div class="text-center pt-3 sm:pt-0">
          <p class="text-xs text-va-muted mb-1">Net Out</p>
          <p class="text-2xl font-semibold text-va-danger" class:privacy-blur={privacyOn}>
            {formatCurrency(-parseFloat(stats.total_expenses))}
          </p>
        </div>
        <div class="text-center pt-3 sm:pt-0">
          <p class="text-xs text-va-muted mb-1">Net Balance</p>
          <p class="text-2xl font-semibold {parseFloat(stats.net_balance) >= 0 ? 'text-va-success' : 'text-va-danger'}" class:privacy-blur={privacyOn}>
            {formatCurrency(parseFloat(stats.net_balance))}
          </p>
        </div>
      </div>
      <p class="text-xs text-va-muted mt-3 text-center">{stats.total_count} transactions</p>
    </Card>
  {/if}

  <!-- Chart -->
  <Card>
    <div class="mb-4">
      <h2 class="text-sm font-medium text-va-text">Net Amount by Category</h2>
    </div>

    {#if loading}
      <div class="flex items-center justify-center h-64">
        <div class="w-5 h-5 border-2 border-va-muted border-t-transparent rounded-full animate-spin"></div>
      </div>
    {:else if !stats?.by_category?.length}
      <div class="text-center py-12">
        <div class="text-3xl mb-2">📊</div>
        <p class="text-va-muted text-sm">No data available</p>
        <p class="text-va-muted text-xs mt-1">Categorize your transactions to see analytics</p>
      </div>
    {:else}
      <div class="h-[400px] md:h-[500px]">
        <canvas bind:this={chartCanvas}></canvas>
      </div>
    {/if}
  </Card>

  <!-- Category Breakdown Table -->
  {#if stats?.by_category?.length}
    <Card class="mt-4">
      <h2 class="text-sm font-medium text-va-text mb-4">Category Breakdown</h2>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-va-border">
              <th class="text-left py-2 px-3 text-xs text-va-muted font-medium">Category</th>
              <th class="text-right py-2 px-3 text-xs text-va-muted font-medium">Transactions</th>
              <th class="text-right py-2 px-3 text-xs text-va-muted font-medium">Net Amount</th>
              {#if stats.period_months > 1}
                <th class="text-right py-2 px-3 text-xs text-va-muted font-medium" title="Average per month over {stats.period_months} months">
                  Avg/month
                </th>
              {/if}
            </tr>
          </thead>
          <tbody>
            {#each [...stats.by_category].sort((a, b) => Math.abs(parseFloat(b.total)) - Math.abs(parseFloat(a.total))) as category}
              <tr
                class="border-b border-va-border/30 hover:bg-va-hover/50 cursor-pointer transition-colors"
                onclick={() => showCategoryTransactions(category)}
                title="Click to view transactions"
              >
                <td class="py-2 px-3">
                  <div class="flex items-center gap-2">
                    {#if category.category_color}
                      <span
                        class="w-3 h-3 rounded-full"
                        style="background-color: {category.category_color}"
                      ></span>
                    {/if}
                    <span class="text-sm text-va-text">{category.category_name}</span>
                  </div>
                </td>
                <td class="py-2 px-3 text-right text-sm text-va-muted">{category.count}</td>
                <td class="py-2 px-3 text-right text-sm font-medium {parseFloat(category.total) >= 0 ? 'text-va-success' : 'text-va-danger'}">
                  {formatCurrency(parseFloat(category.total))}
                </td>
                {#if stats.period_months > 1}
                  <td class="py-2 px-3 text-right text-sm text-va-muted">
                    {formatCurrency(parseFloat(category.total) / stats.period_months)}
                  </td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </Card>
  {/if}
</div>

<!-- Transactions Modal -->
<Modal bind:show={showTransactionsModal} title={selectedCategory?.category_name || 'Transactions'} onClose={closeTransactionsModal}>
  {#if loadingTransactions}
    <div class="flex items-center justify-center py-8">
      <div class="w-5 h-5 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if categoryTransactions.length === 0}
    <p class="text-sm text-va-muted text-center py-4">No transactions found</p>
  {:else}
    <!-- Sort bar -->
    <div class="flex items-center justify-between mb-2 px-1">
      <span class="text-xs text-va-muted">{sortedTransactions.length} transactions</span>
      <button
        onclick={toggleSortAmount}
        class="inline-flex items-center gap-1 text-xs transition-colors {txnSort.by === 'amount' ? 'text-va-accent' : 'text-va-muted hover:text-va-text'}"
      >
        Sort by amount
        {#if txnSort.by === 'amount'}
          <svg class="w-3 h-3 transition-transform {txnSort.order === 'asc' ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        {:else}
          <svg class="w-3 h-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
          </svg>
        {/if}
      </button>
    </div>

    <div class="max-h-[60vh] overflow-auto">
      <div class="space-y-2">
        {#each sortedTransactions as txn}
          <div class="flex items-center justify-between gap-3 p-3 rounded-lg bg-va-hover/30 border border-va-border/50">
            <div class="flex-1 min-w-0">
              <span class="text-xs text-va-muted">{formatDate(txn.transaction_date)}</span>
              <p class="text-sm text-va-text truncate mt-1" class:privacy-blur={privacyOn}>{txn.counterparty_name || 'Unknown'}</p>
              {#if txn.description}
                <p class="text-xs text-va-muted truncate mt-0.5">{txn.description}</p>
              {/if}
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <!-- Category (inline edit) -->
              {#if editingTransactionId === txn.id}
                <select
                  class="text-xs px-2 py-1 rounded-md border border-va-accent bg-va-canvas text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                  value={txn.category_id || ''}
                  onchange={(e) => saveCategory(txn.id, e.target.value ? parseInt(e.target.value) : null)}
                  onblur={cancelEditing}
                  disabled={savingTransaction === txn.id}
                >
                  <option value="">-- Remove category --</option>
                  {#each filterOptions.categories || [] as category}
                    <option value={category.id}>{category.name}</option>
                  {/each}
                </select>
              {:else}
                <button
                  onclick={() => startEditingCategory(txn)}
                  class="text-left hover:bg-va-hover/50 rounded px-1 transition-colors"
                  title="Click to edit category"
                >
                  {#if getCategoryName(txn.category_id)}
                    <span
                      class="text-xs px-2 py-1 rounded-md border inline-block whitespace-nowrap"
                      style={getCategoryColor(txn.category_id) ? `background-color: ${getCategoryColor(txn.category_id)}20; border-color: ${getCategoryColor(txn.category_id)}40; color: ${getCategoryColor(txn.category_id)}` : ''}
                      class:bg-va-hover={!getCategoryColor(txn.category_id)}
                      class:border-va-border={!getCategoryColor(txn.category_id)}
                      class:text-va-muted={!getCategoryColor(txn.category_id)}
                    >
                      {getCategoryName(txn.category_id)}
                    </span>
                  {:else}
                    <span class="text-xs text-va-muted/50 hover:text-va-muted">+ Add</span>
                  {/if}
                </button>
              {/if}

              <p class="text-sm font-medium w-24 text-right {txn.amount >= 0 ? 'text-va-success' : 'text-va-danger'}">
                {formatCurrency(txn.amount)}
              </p>

              <button
                onclick={() => createRuleModal.open(txn)}
                class="p-1.5 text-va-muted hover:text-va-accent hover:bg-va-hover rounded-md transition-all"
                title="Create rule from this transaction"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </button>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</Modal>

<CreateRuleModal bind:this={createRuleModal} categories={filterOptions.categories || []} />
