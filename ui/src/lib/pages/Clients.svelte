<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Button from '../components/Button.svelte'
  import Modal from '../components/Modal.svelte'
  import Input from '../components/Input.svelte'
  import api from '../api.js'

  let clients = $state([])
  let loading = $state(true)
  let showCreateModal = $state(false)
  let showEditModal = $state(false)
  let creating = $state(false)
  let updating = $state(false)
  let editingClientId = $state(null)

  const defaultForm = {
    name: '',
    email: '',
    phone: '',
    address: '',
    city: '',
    postal_code: '',
    country: 'Netherlands',
    vat_number: '',
    chamber_of_commerce: ''
  }

  // Form state
  let form = $state({ ...defaultForm })

  onMount(async () => {
    await loadClients()
  })

  async function loadClients() {
    loading = true
    try {
      clients = await api.clients.list({ active_only: false })
    } catch (error) {
      console.error('Failed to load clients:', error)
    } finally {
      loading = false
    }
  }

  async function createClient() {
    if (!form.name) {
      window.showToast?.('Client name is required', 'error')
      return
    }

    creating = true
    try {
      await api.clients.create(form)
      showCreateModal = false
      resetForm()
      await loadClients()
      window.showToast?.('Client created successfully', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      creating = false
    }
  }

  function resetForm() {
    form = { ...defaultForm }
    editingClientId = null
  }

  function openEditModal(client) {
    editingClientId = client.id
    form = {
      name: client.name || '',
      email: client.email || '',
      phone: client.phone || '',
      address: client.address || '',
      city: client.city || '',
      postal_code: client.postal_code || '',
      country: client.country || '',
      vat_number: client.vat_number || '',
      chamber_of_commerce: client.chamber_of_commerce || ''
    }
    showEditModal = true
  }

  async function updateClient() {
    if (!form.name) {
      window.showToast?.('Client name is required', 'error')
      return
    }

    updating = true
    try {
      await api.clients.update(editingClientId, form)
      showEditModal = false
      resetForm()
      await loadClients()
      window.showToast?.('Client updated successfully', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      updating = false
    }
  }

  async function deleteClient(id) {
    if (!confirm('Are you sure you want to delete this client?')) return

    try {
      await api.clients.delete(id)
      await loadClients()
      window.showToast?.('Client deleted', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }
</script>

<div>
  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
    <h1 class="text-lg font-semibold text-va-text">Clients</h1>
    <Button onclick={() => showCreateModal = true}>
      New Client
    </Button>
  </div>

  <Card>
    {#if loading}
      <div class="flex items-center justify-center h-24">
        <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    {:else if clients.length === 0}
      <div class="text-center py-8">
        <span class="icon-[tabler--users] w-8 h-8 text-va-muted mb-3 inline-block"></span>
        <p class="text-va-muted text-sm">No clients yet</p>
        <p class="text-va-muted text-sm mt-1">Add your first client to create invoices</p>
      </div>
    {:else}
      <div class="space-y-2">
        {#each clients as client}
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-4 bg-va-hover/50 rounded-lg border border-va-border/30 hover:border-va-border transition-all">
            <div>
              <div class="text-sm text-va-text font-medium">{client.name}</div>
              <div class="text-sm text-va-muted mt-0.5">
                {#if client.email}{client.email}{/if}
                {#if client.email && client.city} · {/if}
                {#if client.city}{client.city}{/if}
              </div>
              {#if client.vat_number}
                <div class="text-xs text-va-muted mt-1">VAT: {client.vat_number}</div>
              {/if}
            </div>
            <div class="flex items-center gap-2">
              {#if !client.is_active}
                <span class="badge badge-sm badge-soft badge-secondary">Inactive</span>
              {/if}
              <button
                onclick={() => openEditModal(client)}
                class="p-2 text-va-muted hover:text-va-accent hover:bg-va-accent/10 rounded-lg transition-all"
                title="Edit client"
              >
                <span class="icon-[tabler--edit] w-4 h-4"></span>
              </button>
              <button
                onclick={() => deleteClient(client.id)}
                class="p-2 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded-lg transition-all"
                title="Delete client"
              >
                <span class="icon-[tabler--trash] w-4 h-4"></span>
              </button>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </Card>
</div>

<!-- Create Client Modal -->
<Modal bind:show={showCreateModal} title="Add Client" onClose={resetForm}>
  <Input
    label="Name"
    bind:value={form.name}
    placeholder="Company or person name"
    required
  />

  <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
    <Input
      label="Email"
      type="email"
      bind:value={form.email}
      placeholder="email@example.com"
    />
    <Input
      label="Phone"
      bind:value={form.phone}
      placeholder="+31 6 12345678"
    />
  </div>

  <Input
    label="Address"
    bind:value={form.address}
    placeholder="Street address"
  />

  <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
    <Input
      label="City"
      bind:value={form.city}
      placeholder="City"
    />
    <Input
      label="Postal Code"
      bind:value={form.postal_code}
      placeholder="1234 AB"
    />
    <Input
      label="Country"
      bind:value={form.country}
      placeholder="Country"
    />
  </div>

  <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
    <Input
      label="VAT Number"
      bind:value={form.vat_number}
      placeholder="NL123456789B01"
    />
    <Input
      label="Chamber of Commerce"
      bind:value={form.chamber_of_commerce}
      placeholder="12345678"
    />
  </div>

  <div class="flex gap-3 mt-5 pt-4 border-t border-va-border">
    <Button onclick={createClient} loading={creating}>
      Add Client
    </Button>
    <Button variant="secondary" onclick={() => showCreateModal = false}>
      Cancel
    </Button>
  </div>
</Modal>

<!-- Edit Client Modal -->
<Modal bind:show={showEditModal} title="Edit Client" onClose={resetForm}>
  <Input
    label="Name"
    bind:value={form.name}
    placeholder="Company or person name"
    required
  />

  <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
    <Input
      label="Email"
      type="email"
      bind:value={form.email}
      placeholder="email@example.com"
    />
    <Input
      label="Phone"
      bind:value={form.phone}
      placeholder="+31 6 12345678"
    />
  </div>

  <Input
    label="Address"
    bind:value={form.address}
    placeholder="Street address"
  />

  <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
    <Input
      label="City"
      bind:value={form.city}
      placeholder="City"
    />
    <Input
      label="Postal Code"
      bind:value={form.postal_code}
      placeholder="1234 AB"
    />
    <Input
      label="Country"
      bind:value={form.country}
      placeholder="Country"
    />
  </div>

  <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
    <Input
      label="VAT Number"
      bind:value={form.vat_number}
      placeholder="NL123456789B01"
    />
    <Input
      label="Chamber of Commerce"
      bind:value={form.chamber_of_commerce}
      placeholder="12345678"
    />
  </div>

  <div class="flex gap-3 mt-5 pt-4 border-t border-va-border">
    <Button onclick={updateClient} loading={updating}>
      Save Changes
    </Button>
    <Button variant="secondary" onclick={() => showEditModal = false}>
      Cancel
    </Button>
  </div>
</Modal>
