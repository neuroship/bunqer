<script>
  import { onMount } from 'svelte'
  import { passkeys } from '../api.js'
  import Button from '../components/Button.svelte'
  import Input from '../components/Input.svelte'

  let { onLogin = () => {} } = $props()

  let error = $state('')
  let loading = $state(false)
  let checking = $state(true)
  let supported = $state(true)
  let registered = $state(true)
  let enrollmentAvailable = $state(false)

  // Enrollment (only when no passkey exists yet)
  let enrollmentToken = $state('')
  let passkeyName = $state('')
  let enrolling = $state(false)

  onMount(async () => {
    supported = passkeys.isSupported()
    try {
      const status = await passkeys.status()
      registered = status.registered
      enrollmentAvailable = status.enrollment_available
    } catch (e) {
      error = e.message || 'Could not reach the server'
    } finally {
      checking = false
    }
  })

  async function handleLogin() {
    error = ''
    loading = true
    try {
      await passkeys.login()
      onLogin()
    } catch (e) {
      if (e.name === 'NotAllowedError') {
        error = 'Passkey sign-in was cancelled.'
      } else {
        error = e.message || 'Passkey sign-in failed'
      }
    } finally {
      loading = false
    }
  }

  async function handleEnroll() {
    error = ''
    enrolling = true
    try {
      await passkeys.register(passkeyName || undefined, enrollmentToken)
      enrollmentToken = ''
      passkeyName = ''
      registered = true
      enrollmentAvailable = false
      await handleLogin()
    } catch (e) {
      if (e.name === 'NotAllowedError') {
        error = 'Passkey registration was cancelled.'
      } else {
        error = e.message || 'Passkey registration failed'
      }
    } finally {
      enrolling = false
    }
  }
</script>

<div class="min-h-screen bg-va-canvas flex items-center justify-center p-4">
  <div class="w-full max-w-sm">
    <div class="card p-8">
      <div class="text-center mb-8">
        <h1 class="text-2xl font-semibold text-va-text mb-2">Bunqer</h1>
        <p class="text-va-muted text-sm">
          {registered ? 'Sign in with your passkey' : 'Register your first passkey'}
        </p>
      </div>

      {#if error}
        <div class="mb-4 p-3 bg-va-danger/10 border border-va-danger/20 rounded-lg">
          <p class="text-sm text-va-danger">{error}</p>
        </div>
      {/if}

      <div class="flex justify-center mb-6">
        <svg class="w-12 h-12 text-va-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z" />
        </svg>
      </div>

      {#if !supported}
        <p class="text-sm text-va-muted text-center">
          This browser does not support passkeys. Use a browser with WebAuthn support.
        </p>
      {:else if checking}
        <div class="flex items-center justify-center gap-2 text-sm text-va-muted">
          <span class="inline-block w-4 h-4 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></span>
          Checking...
        </div>
      {:else if registered}
        <Button
          type="button"
          variant="primary"
          class="w-full"
          {loading}
          disabled={loading}
          onclick={handleLogin}
        >
          {loading ? 'Waiting for passkey...' : 'Sign in with passkey'}
        </Button>
      {:else if enrollmentAvailable}
        <p class="text-sm text-va-muted mb-4">
          No passkey registered yet. Enter the enrollment token from the API environment to register one.
        </p>
        <Input
          label="Enrollment token"
          type="password"
          bind:value={enrollmentToken}
          placeholder="PASSKEY_ENROLLMENT_TOKEN"
          disabled={enrolling}
        />
        <Input
          label="Passkey name"
          type="text"
          bind:value={passkeyName}
          placeholder="MacBook Touch ID"
          disabled={enrolling}
        />
        <Button
          type="button"
          variant="primary"
          class="w-full mt-4"
          loading={enrolling}
          disabled={enrolling || !enrollmentToken}
          onclick={handleEnroll}
        >
          {enrolling ? 'Waiting for passkey...' : 'Register passkey'}
        </Button>
      {:else}
        <p class="text-sm text-va-muted text-center">
          No passkey is registered and enrollment is closed. Set PASSKEY_ENROLLMENT_TOKEN in the API
          environment, restart it, then reload this page.
        </p>
      {/if}
    </div>

    <p class="text-center text-va-muted text-xs mt-6">
      Passkey-only authentication
    </p>
  </div>
</div>
