<script>
  let { message = '', type = 'info' } = $props()

  const types = {
    info: 'bg-va-subtle border-va-border text-va-text',
    success: 'bg-va-success/15 border-va-success/40 text-va-success',
    error: 'bg-va-danger/15 border-va-danger/40 text-va-danger',
    warning: 'bg-va-warning/15 border-va-warning/40 text-va-warning'
  }
</script>

<div class="fixed bottom-4 right-4 z-50 animate-fade-in">
  <div class="px-4 py-3 rounded-xl border text-sm {types[type]} shadow-medium backdrop-blur-sm">
    {message}
  </div>
</div>

<style>
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px) scale(0.95); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  .animate-fade-in {
    animation: fadeIn 0.25s ease-out;
  }
</style>
