<script>
  import { onMount, onDestroy } from 'svelte'
  import { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend } from 'chart.js'
  import Card from '../components/Card.svelte'
  import Modal from '../components/Modal.svelte'
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

    try {
      const { start_date, end_date } = getDateRange()
      const params = {
        limit: 100
      }

      if (filters.account_id) {
        params.account_id = filters.account_id
      }
      if (start_date) {
        params.start_date = start_date
      }
      if (end_date) {
        params.end_date = end_date
      }

      // Handle uncategorized (null category_id)
      if (category.category_id === null) {
        params.category_id = 'none'
      } else {
        params.category_id = category.category_id
      }

      const response = await api.transactions.list(params)
      categoryTransactions = response.items
    } catch (error) {
      console.error('Failed to load transactions:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      loadingTransactions = false
    }
  }

  function closeTransactionsModal() {
    showTransactionsModal = false
    selectedCategory = null
    categoryTransactions = []
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
      <div class="text-center">
        <p class="text-xs text-va-muted mb-1">Net Balance</p>
        <p class="text-2xl font-semibold {parseFloat(stats.net_balance) >= 0 ? 'text-va-success' : 'text-va-danger'}" class:privacy-blur={privacyOn}>
          {formatCurrency(parseFloat(stats.net_balance))}
        </p>
        <p class="text-xs text-va-muted mt-2">{stats.total_count} transactions</p>
      </div>
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
  <div class="max-h-[60vh] overflow-auto">
    {#if loadingTransactions}
      <div class="flex items-center justify-center py-8">
        <div class="w-5 h-5 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    {:else if categoryTransactions.length === 0}
      <p class="text-sm text-va-muted text-center py-4">No transactions found</p>
    {:else}
      <div class="space-y-2">
        {#each categoryTransactions as txn}
          <div class="flex items-center justify-between p-3 rounded-lg bg-va-hover/30 border border-va-border/50">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-xs text-va-muted">{formatDate(txn.transaction_date)}</span>
              </div>
              <p class="text-sm text-va-text truncate mt-1" class:privacy-blur={privacyOn}>{txn.counterparty_name || 'Unknown'}</p>
              {#if txn.description}
                <p class="text-xs text-va-muted truncate mt-0.5">{txn.description}</p>
              {/if}
            </div>
            <div class="text-right ml-4">
              <p class="text-sm font-medium {txn.amount >= 0 ? 'text-va-success' : 'text-va-danger'}">
                {formatCurrency(txn.amount)}
              </p>
            </div>
          </div>
        {/each}
      </div>
      {#if categoryTransactions.length >= 100}
        <p class="text-xs text-va-muted text-center mt-4">Showing first 100 transactions</p>
      {/if}
    {/if}
  </div>
</Modal>
