<script>
  import { onMount, onDestroy } from 'svelte'
  import Sidebar from './lib/components/Sidebar.svelte'
  import Onboarding from './lib/pages/Onboarding.svelte'
  import Transactions from './lib/pages/Transactions.svelte'
  import Analytics from './lib/pages/Analytics.svelte'
  import Invoices from './lib/pages/Invoices.svelte'
  import Clients from './lib/pages/Clients.svelte'
  import Categories from './lib/pages/Categories.svelte'
  import Settings from './lib/pages/Settings.svelte'
  import Login from './lib/pages/Login.svelte'
  import Toast from './lib/components/Toast.svelte'
  import { subscribeToEvents, isAuthenticated, clearAuth, setOnUnauthorized, getUsername } from './lib/api.js'

  let currentPage = $state('transactions')
  let toast = $state({ show: false, message: '', type: 'info' })
  let syncStatus = $state('')
  let authenticated = $state(isAuthenticated())
  let username = $state(getUsername())
  let unsubscribe = null

  function navigate(page) {
    currentPage = page
  }

  function showToast(message, type = 'info') {
    toast = { show: true, message, type }
    setTimeout(() => {
      toast = { ...toast, show: false }
    }, 4000)
  }

  function handleLogin() {
    authenticated = true
    username = getUsername()
    showToast(`Welcome, ${username}!`, 'success')
  }

  function handleLogout() {
    clearAuth()
    authenticated = false
    username = null
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
    showToast('Logged out successfully', 'info')
  }

  function handleUnauthorized() {
    authenticated = false
    username = null
    showToast('Session expired. Please log in again.', 'error')
  }

  function handleEvent(event) {
    console.log('SSE Event:', event)

    switch (event.type) {
      case 'auto_sync_started':
        syncStatus = event.data.message
        break
      case 'sync_started':
        syncStatus = `Syncing ${event.data.account_name}...`
        break
      case 'sync_progress':
        syncStatus = `${event.data.account_name}: ${event.data.fetched} fetched, ${event.data.new} new`
        break
      case 'sync_completed':
        // Don't clear status yet - wait for auto_sync_completed
        break
      case 'auto_sync_completed':
        syncStatus = ''
        if (event.data.total_new > 0) {
          showToast(event.data.message, 'success')
          // Trigger page refresh to show new data
          window.dispatchEvent(new CustomEvent('transactions-updated'))
        } else {
          showToast(event.data.message, 'info')
        }
        break
      case 'sync_error':
      case 'auto_sync_error':
        syncStatus = ''
        showToast(event.data.message, 'error')
        break
      case 'notification':
        showToast(event.data.message, event.data.level || 'info')
        break
    }
  }

  // Make showToast available globally and subscribe to events
  onMount(() => {
    window.showToast = showToast
    setOnUnauthorized(handleUnauthorized)

    // Only subscribe to events if authenticated
    if (authenticated) {
      unsubscribe = subscribeToEvents(handleEvent)
    }
  })

  // Re-subscribe when authentication changes
  $effect(() => {
    if (authenticated && !unsubscribe) {
      unsubscribe = subscribeToEvents(handleEvent)
    }
  })

  onDestroy(() => {
    if (unsubscribe) unsubscribe()
  })
</script>

{#if !authenticated}
  <Login onLogin={handleLogin} />
{:else}
  <div class="flex min-h-screen bg-va-canvas">
    <Sidebar {currentPage} onNavigate={navigate} {username} onLogout={handleLogout} />

    <main class="flex-1 p-6">
      {#if syncStatus}
        <div class="fixed top-4 right-4 z-40 bg-va-subtle border border-va-border rounded-lg px-4 py-2 flex items-center gap-3 shadow-soft">
          <div class="w-4 h-4 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
          <span class="text-sm text-va-muted">{syncStatus}</span>
        </div>
      {/if}
      {#if currentPage === 'onboarding'}
        <Onboarding />
      {:else if currentPage === 'transactions'}
        <Transactions />
      {:else if currentPage === 'analytics'}
        <Analytics />
      {:else if currentPage === 'invoices'}
        <Invoices />
      {:else if currentPage === 'clients'}
        <Clients />
      {:else if currentPage === 'categories'}
        <Categories />
      {:else if currentPage === 'settings'}
        <Settings />
      {/if}
    </main>
  </div>
{/if}

{#if toast.show}
  <Toast message={toast.message} type={toast.type} />
{/if}
