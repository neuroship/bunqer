<script>
  let {
    type = 'text',
    label = '',
    placeholder = '',
    value = $bindable(''),
    required = false,
    disabled = false,
    error = '',
    class: className = ''
  } = $props()
</script>

<div class="mb-3 {className}">
  {#if label}
    <label class="block text-sm text-va-muted mb-1.5">
      {label}
      {#if required}<span class="text-va-danger">*</span>{/if}
    </label>
  {/if}

  {#if type === 'textarea'}
    <textarea
      bind:value
      {placeholder}
      {required}
      {disabled}
      rows="3"
      class="input input-sm bg-va-canvas border-va-border text-va-text w-full resize-none {error ? 'border-va-danger' : ''}"
    ></textarea>
  {:else}
    <input
      {type}
      bind:value
      {placeholder}
      {required}
      {disabled}
      class="input input-sm bg-va-canvas border-va-border text-va-text w-full {error ? 'border-va-danger' : ''}"
    />
  {/if}

  {#if error}
    <p class="mt-1 text-xs text-va-danger">{error}</p>
  {/if}
</div>
