<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Button from '../components/Button.svelte'
  import Input from '../components/Input.svelte'
  import api from '../api.js'
  import { passkeys } from '../api.js'
  import { getPrivacyMode } from '../privacy.svelte.js'

  let privacyOn = $derived(getPrivacyMode())

  let loading = $state(true)
  let saving = $state(false)
  let uploadingLogo = $state(false)

  // Passkey state
  let registeredPasskeys = $state([])
  let loadingPasskeys = $state(false)
  let registeringPasskey = $state(false)
  let newPasskeyName = $state('')
  let passkeySupported = $state(false)

  let form = $state({
    name: '',
    address: '',
    city: '',
    postal_code: '',
    country: 'Netherlands',
    vat_number: '',
    chamber_of_commerce: '',
    email: '',
    phone: '',
    website: '',
    iban: '',
    bank_name: ''
  })

  let hasLogo = $state(false)
  let logoPreview = $state(null)
  let fileInput

  onMount(async () => {
    passkeySupported = passkeys.isSupported()

    try {
      const settings = await api.companySettings.get()
      form = {
        name: settings.name || '',
        address: settings.address || '',
        city: settings.city || '',
        postal_code: settings.postal_code || '',
        country: settings.country || 'Netherlands',
        vat_number: settings.vat_number || '',
        chamber_of_commerce: settings.chamber_of_commerce || '',
        email: settings.email || '',
        phone: settings.phone || '',
        website: settings.website || '',
        iban: settings.iban || '',
        bank_name: settings.bank_name || ''
      }
      hasLogo = settings.has_logo
      if (settings.logo_base64) logoPreview = settings.logo_base64
    } catch (error) {
      console.error('Failed to load settings:', error)
    } finally {
      loading = false
    }

    if (passkeySupported) {
      await loadPasskeys()
    }
  })

  async function loadPasskeys() {
    loadingPasskeys = true
    try {
      registeredPasskeys = await passkeys.list()
    } catch (error) {
      console.error('Failed to load passkeys:', error)
    } finally {
      loadingPasskeys = false
    }
  }

  async function registerPasskey() {
    registeringPasskey = true
    try {
      await passkeys.register(newPasskeyName || undefined)
      newPasskeyName = ''
      await loadPasskeys()
      window.showToast?.('Passkey registered successfully', 'success')
    } catch (error) {
      if (error.name === 'NotAllowedError') {
        window.showToast?.('Passkey registration was cancelled', 'info')
      } else {
        window.showToast?.(error.message || 'Failed to register passkey', 'error')
      }
    } finally {
      registeringPasskey = false
    }
  }

  async function deletePasskey(id, name) {
    if (!confirm(`Delete passkey "${name}"?`)) return
    try {
      await passkeys.delete(id)
      await loadPasskeys()
      window.showToast?.('Passkey deleted', 'success')
    } catch (error) {
      window.showToast?.(error.message || 'Failed to delete passkey', 'error')
    }
  }

  async function saveSettings() {
    saving = true
    try {
      const settings = await api.companySettings.update(form)
      hasLogo = settings.has_logo
      window.showToast?.('Company settings saved', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      saving = false
    }
  }

  async function handleLogoUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return

    uploadingLogo = true
    try {
      const settings = await api.companySettings.uploadLogo(file)
      hasLogo = true
      // Show preview
      const reader = new FileReader()
      reader.onload = (ev) => { logoPreview = ev.target.result }
      reader.readAsDataURL(file)
      window.showToast?.('Logo uploaded', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      uploadingLogo = false
      if (fileInput) fileInput.value = ''
    }
  }

  async function removeLogo() {
    try {
      await api.companySettings.deleteLogo()
      hasLogo = false
      logoPreview = null
      window.showToast?.('Logo removed', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }
</script>

<div>
  <div class="mb-4">
    <h1 class="text-lg font-semibold text-va-text">Company Settings</h1>
    <p class="text-sm text-va-muted mt-1">This information appears on your invoices</p>
  </div>

  {#if loading}
    <Card>
      <div class="flex items-center justify-center h-24">
        <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    </Card>
  {:else}
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">

      <!-- Logo -->
      <Card>
        <h3 class="text-sm font-medium text-va-text mb-3">Company Logo</h3>
        <p class="text-xs text-va-muted mb-4">PNG, JPEG, WebP, or SVG. Max 2MB. Appears on invoice PDFs.</p>

        <div class="flex flex-col items-center gap-3">
          {#if logoPreview}
            <div class="w-32 h-32 rounded-lg border border-va-border bg-white flex items-center justify-center overflow-hidden">
              <img src={logoPreview} alt="Company logo" class="max-w-full max-h-full object-contain" />
            </div>
            <button onclick={removeLogo} class="text-xs text-va-danger hover:text-va-danger/80 transition-colors">
              Remove logo
            </button>
          {:else}
            <div
              class="w-32 h-32 rounded-lg border-2 border-dashed border-va-border hover:border-va-accent/50 bg-va-canvas/50 flex flex-col items-center justify-center cursor-pointer transition-colors"
              onclick={() => fileInput?.click()}
              role="button"
              tabindex="0"
              onkeydown={(e) => e.key === 'Enter' && fileInput?.click()}
            >
              <svg class="w-8 h-8 text-va-muted mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span class="text-xs text-va-muted">Upload logo</span>
            </div>
          {/if}

          {#if uploadingLogo}
            <div class="w-5 h-5 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
          {:else if !logoPreview}
            <Button variant="secondary" onclick={() => fileInput?.click()} class="text-xs">
              Choose File
            </Button>
          {:else}
            <Button variant="secondary" onclick={() => fileInput?.click()} class="text-xs">
              Replace
            </Button>
          {/if}
        </div>

        <input
          bind:this={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/svg+xml"
          onchange={handleLogoUpload}
          class="hidden"
        />
      </Card>

      <!-- Company Details -->
      <Card class="lg:col-span-2">
        <h3 class="text-sm font-medium text-va-text mb-4">Company Details</h3>

        <div class="grid grid-cols-2 gap-x-4 gap-y-0" class:privacy-blur={privacyOn}>
          <Input label="Company Name" bind:value={form.name} placeholder="Your Company B.V." />
          <Input label="Email" bind:value={form.email} placeholder="info@yourcompany.nl" />
          <Input label="Address" bind:value={form.address} placeholder="Streetname 123" />
          <Input label="Phone" bind:value={form.phone} placeholder="+31 6 12345678" />
          <Input label="City" bind:value={form.city} placeholder="Amsterdam" />
          <Input label="Website" bind:value={form.website} placeholder="www.yourcompany.nl" />
          <Input label="Postal Code" bind:value={form.postal_code} placeholder="1012 AB" />
          <Input label="Country" bind:value={form.country} placeholder="Netherlands" />
        </div>

        <h3 class="text-sm font-medium text-va-text mb-4 mt-2 pt-3 border-t border-va-border">Tax & Legal</h3>
        <div class="grid grid-cols-2 gap-x-4 gap-y-0" class:privacy-blur={privacyOn}>
          <Input label="VAT Number" bind:value={form.vat_number} placeholder="NL123456789B01" />
          <Input label="KvK Number" bind:value={form.chamber_of_commerce} placeholder="12345678" />
        </div>

        <h3 class="text-sm font-medium text-va-text mb-4 mt-2 pt-3 border-t border-va-border">Bank Details</h3>
        <div class="grid grid-cols-2 gap-x-4 gap-y-0" class:privacy-blur={privacyOn}>
          <Input label="IBAN" bind:value={form.iban} placeholder="NL00 BANK 1234 5678 90" />
          <Input label="Bank Name" bind:value={form.bank_name} placeholder="ING Bank" />
        </div>

        <div class="flex justify-end mt-4 pt-3 border-t border-va-border">
          <Button onclick={saveSettings} loading={saving}>
            Save Settings
          </Button>
        </div>
      </Card>
    </div>

    <!-- Passkeys / MFA -->
    {#if passkeySupported}
      <div class="mt-4">
        <Card>
          <h3 class="text-sm font-medium text-va-text mb-1">Passkeys</h3>
          <p class="text-xs text-va-muted mb-4">Use biometrics or a security key to sign in without a password.</p>

          {#if loadingPasskeys}
            <div class="flex items-center justify-center h-16">
              <div class="w-5 h-5 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
            </div>
          {:else}
            {#if registeredPasskeys.length > 0}
              <div class="space-y-2 mb-4">
                {#each registeredPasskeys as pk (pk.id)}
                  <div class="flex items-center justify-between p-3 bg-va-canvas rounded-lg border border-va-border">
                    <div class="flex items-center gap-3">
                      <svg class="w-5 h-5 text-va-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z" />
                      </svg>
                      <div>
                        <p class="text-sm text-va-text font-medium">{pk.name || 'Passkey'}</p>
                        <p class="text-xs text-va-muted">Added {new Date(pk.created_at).toLocaleDateString()}</p>
                      </div>
                    </div>
                    <button
                      onclick={() => deletePasskey(pk.id, pk.name)}
                      class="text-xs text-va-danger hover:text-va-danger/80 transition-colors"
                    >
                      Remove
                    </button>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="mb-4 p-3 bg-va-canvas rounded-lg border border-va-border text-center">
                <p class="text-sm text-va-muted">No passkeys registered yet.</p>
              </div>
            {/if}

            <div class="flex items-end gap-2">
              <div class="flex-1">
                <Input
                  label="Passkey name"
                  bind:value={newPasskeyName}
                  placeholder="e.g. MacBook Touch ID"
                  disabled={registeringPasskey}
                />
              </div>
              <div class="pb-3">
                <Button
                  onclick={registerPasskey}
                  loading={registeringPasskey}
                  variant="secondary"
                >
                  {registeringPasskey ? 'Waiting...' : 'Add Passkey'}
                </Button>
              </div>
            </div>
          {/if}
        </Card>
      </div>
    {/if}
  {/if}
</div>
