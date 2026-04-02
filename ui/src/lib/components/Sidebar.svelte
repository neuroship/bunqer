<script>
  import { getPrivacyMode, togglePrivacyMode } from '../privacy.svelte.js'

  let { currentPage, onNavigate, username = null, onLogout = () => {} } = $props()

  let privacyOn = $derived(getPrivacyMode())

  const menuItems = [
    { id: 'transactions', label: 'Transactions', icon: 'icon-[tabler--credit-card]' },
    { id: 'analytics', label: 'Analytics', icon: 'icon-[tabler--chart-bar]' },
    { id: 'invoices', label: 'Invoices', icon: 'icon-[tabler--file-text]' },
    { id: 'clients', label: 'Clients', icon: 'icon-[tabler--users]' },
    { id: 'categories', label: 'Categories', icon: 'icon-[tabler--tags]' },
    { id: 'settings', label: 'Settings', icon: 'icon-[tabler--building]' },
    { id: 'onboarding', label: 'Setup', icon: 'icon-[tabler--settings]' }
  ]
</script>

<aside class="w-56 bg-va-subtle border-r border-va-border h-screen flex flex-col sticky top-0">
  <div class="px-5 py-4 border-b border-va-border">
    <h1 class="text-base font-semibold text-va-text">Bunqer</h1>
    <p class="text-xs text-va-muted mt-1">Financial Management</p>
  </div>

  <nav class="p-3 flex-1">
    <ul class="space-y-1">
      {#each menuItems as item}
        <li>
          <button
            onclick={() => onNavigate(item.id)}
            class="w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-left text-sm transition-all
                   {currentPage === item.id
                     ? 'bg-va-active text-va-text shadow-soft'
                     : 'text-va-muted hover:bg-va-hover hover:text-va-text'}"
          >
            <span class="{item.icon} w-4 h-4"></span>
            <span>{item.label}</span>
          </button>
        </li>
      {/each}
    </ul>
  </nav>

  {#if username}
    <div class="p-3 border-t border-va-border">
      <div class="flex items-center justify-between px-4 py-2">
        <div class="flex items-center gap-2 min-w-0">
          <div class="w-7 h-7 rounded-full bg-va-accent/20 flex items-center justify-center flex-shrink-0">
            <span class="text-xs text-va-accent font-medium">{username.charAt(0).toUpperCase()}</span>
          </div>
          <span class="text-sm text-va-muted truncate">{username}</span>
        </div>
        <div class="flex items-center gap-1 flex-shrink-0 ml-2">
          <button
            onclick={togglePrivacyMode}
            class="p-1 rounded-md transition-colors {privacyOn ? 'text-va-accent' : 'text-va-muted hover:text-va-text'}"
            title={privacyOn ? 'Show sensitive info' : 'Hide sensitive info'}
          >
            <span class="{privacyOn ? 'icon-[tabler--eye-off]' : 'icon-[tabler--eye]'} w-4 h-4"></span>
          </button>
          <button
            onclick={onLogout}
            class="p-1 rounded-md text-va-muted hover:text-va-danger transition-colors"
            title="Logout"
          >
            <span class="icon-[tabler--logout] w-4 h-4"></span>
          </button>
        </div>
      </div>
    </div>
  {/if}
</aside>
