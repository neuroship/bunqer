<script>
  let { show = $bindable(false), title = '', size = 'md', onClose = () => {} } = $props()

  const sizeClasses = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
    '3xl': 'max-w-3xl',
    '4xl': 'max-w-4xl'
  }

  function handleClose() {
    show = false
    onClose()
  }

  function handleBackdropClick(e) {
    if (e.target === e.currentTarget) {
      handleClose()
    }
  }
</script>

{#if show}
  <div
    class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
    onclick={handleBackdropClick}
    role="dialog"
    aria-modal="true"
  >
    <div class="bg-va-subtle rounded-xl border border-va-border {sizeClasses[size] || 'max-w-md'} w-full max-h-[90vh] flex flex-col shadow-medium">
      <div class="flex items-center justify-between p-5 pb-4 border-b border-va-border shrink-0">
        <h3 class="text-base font-semibold text-va-text">{title}</h3>
        <button
          onclick={handleClose}
          class="text-va-muted hover:text-va-text p-1 rounded-lg hover:bg-va-hover transition-colors"
          aria-label="Close"
        >
          <span class="icon-[tabler--x] w-5 h-5"></span>
        </button>
      </div>
      <div class="p-5 pt-4 overflow-y-auto">
        <slot />
      </div>
    </div>
  </div>
{/if}
