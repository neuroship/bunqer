<script>
  let { title = '', class: className = '' } = $props()
</script>

<div class="card bg-va-subtle border border-va-border shadow-soft p-4 {className}">
  {#if title}
    <h2 class="text-base font-semibold text-va-text mb-3">{title}</h2>
  {/if}
  <slot />
</div>
