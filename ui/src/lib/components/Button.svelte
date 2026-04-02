<script>
  let {
    type = 'button',
    variant = 'primary',
    disabled = false,
    loading = false,
    class: className = '',
    onclick = () => {}
  } = $props()

  const variants = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    success: 'btn-success',
    danger: 'btn-error btn-soft'
  }
</script>

<button
  {type}
  {disabled}
  {onclick}
  class="btn btn-sm {variants[variant]} {className} {loading ? 'opacity-75 cursor-wait' : ''}"
>
  {#if loading}
    <span class="loading loading-spinner loading-xs"></span>
  {/if}
  <slot />
</button>
