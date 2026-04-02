<script>
  import { auth, passkeys } from '../api.js'
  import Button from '../components/Button.svelte'
  import Input from '../components/Input.svelte'

  let { onLogin = () => {} } = $props()

  let username = $state('')
  let password = $state('')
  let error = $state('')
  let loading = $state(false)
  let mfaStep = $state(false)
  let mfaLoading = $state(false)

  async function handleSubmit(event) {
    event.preventDefault()
    error = ''
    loading = true

    try {
      const response = await auth.login(username, password)

      if (response.mfa_required) {
        // Password OK — now need passkey verification
        mfaStep = true
        loading = false
        await handleMfa(response.mfa_token)
      } else {
        onLogin()
      }
    } catch (e) {
      error = e.message || 'Login failed'
      loading = false
    }
  }

  async function handleMfa(mfaToken) {
    error = ''
    mfaLoading = true
    try {
      await passkeys.verifyMfa(mfaToken)
      onLogin()
    } catch (e) {
      if (e.name === 'NotAllowedError') {
        error = 'Passkey verification was cancelled. Please try again.'
      } else {
        error = e.message || 'Passkey verification failed'
      }
      // Stay on MFA step so they can retry password
      mfaStep = false
    } finally {
      mfaLoading = false
    }
  }
</script>

<div class="min-h-screen bg-va-canvas flex items-center justify-center p-4">
  <div class="w-full max-w-sm">
    <div class="card p-8">
      <div class="text-center mb-8">
        <h1 class="text-2xl font-semibold text-va-text mb-2">Bunqer</h1>
        <p class="text-va-muted text-sm">
          {mfaStep ? 'Verify your identity with a passkey' : 'Sign in to your account'}
        </p>
      </div>

      {#if error}
        <div class="mb-4 p-3 bg-va-danger/10 border border-va-danger/20 rounded-lg">
          <p class="text-sm text-va-danger">{error}</p>
        </div>
      {/if}

      {#if mfaStep}
        <div class="text-center py-4">
          <div class="flex justify-center mb-4">
            <svg class="w-12 h-12 text-va-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z" />
            </svg>
          </div>
          <p class="text-sm text-va-muted mb-4">
            Password verified. Use your passkey to complete sign-in.
          </p>
          {#if mfaLoading}
            <div class="flex items-center justify-center gap-2 text-sm text-va-muted">
              <span class="inline-block w-4 h-4 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></span>
              Waiting for passkey...
            </div>
          {/if}
        </div>
      {:else}
        <form onsubmit={handleSubmit}>
          <Input
            label="Username"
            type="text"
            bind:value={username}
            placeholder="Enter your username"
            required
            disabled={loading}
          />

          <Input
            label="Password"
            type="password"
            bind:value={password}
            placeholder="Enter your password"
            required
            disabled={loading}
          />

          <Button
            type="submit"
            variant="primary"
            class="w-full mt-4"
            {loading}
            disabled={loading || !username || !password}
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      {/if}
    </div>

    <p class="text-center text-va-muted text-xs mt-6">
      Secure single-user authentication
    </p>
  </div>
</div>
