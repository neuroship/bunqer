<script>
  import Modal from './Modal.svelte'
  import api from '../api.js'

  let { categories = [] } = $props()

  let show = $state(false)
  let savingRule = $state(false)
  let ruleTargetCategoryId = $state('')
  let ruleMode = $state('create') // 'create' or 'existing'
  let existingRules = $state([])
  let loadingExistingRules = $state(false)
  let selectedExistingRuleId = $state('')
  let newConditions = $state([]) // conditions to append in 'existing' mode
  let ruleForm = $state({
    name: '',
    match: 'all',
    conditions: [{ field: 'description', operator: 'contains', value: '' }],
    is_active: true,
    priority: 0
  })

  const fieldOptions = [
    { value: 'description', label: 'Description' },
    { value: 'counterparty_name', label: 'Counterparty Name' },
    { value: 'counterparty_iban', label: 'Counterparty IBAN' },
    { value: 'account_name', label: 'Account Name' },
    { value: 'amount', label: 'Amount' },
    { value: 'direction', label: 'Direction' },
    { value: 'type', label: 'Type' },
    { value: 'sub_type', label: 'Sub Type' }
  ]

  const operatorOptions = {
    description: [
      { value: 'contains', label: 'contains' },
      { value: 'not_contains', label: 'does not contain' },
      { value: 'equals', label: 'equals' },
      { value: 'starts_with', label: 'starts with' },
      { value: 'ends_with', label: 'ends with' }
    ],
    counterparty_name: [
      { value: 'contains', label: 'contains' },
      { value: 'equals', label: 'equals' },
      { value: 'starts_with', label: 'starts with' }
    ],
    counterparty_iban: [
      { value: 'equals', label: 'equals' },
      { value: 'starts_with', label: 'starts with' }
    ],
    account_name: [
      { value: 'equals', label: 'equals' },
      { value: 'contains', label: 'contains' }
    ],
    amount: [
      { value: 'equals', label: 'equals' },
      { value: 'greater_than', label: 'greater than' },
      { value: 'less_than', label: 'less than' }
    ],
    direction: [
      { value: 'equals', label: 'is' }
    ],
    type: [
      { value: 'equals', label: 'equals' }
    ],
    sub_type: [
      { value: 'equals', label: 'equals' }
    ]
  }

  export function open(transaction) {
    const conditions = []
    if (transaction.counterparty_name) {
      conditions.push({ field: 'counterparty_name', operator: 'contains', value: transaction.counterparty_name })
    }
    if (transaction.description) {
      conditions.push({ field: 'description', operator: 'contains', value: transaction.description })
    }
    if (conditions.length === 0) {
      conditions.push({ field: 'description', operator: 'contains', value: '' })
    }

    const ruleName = transaction.counterparty_name
      ? `Rule for ${transaction.counterparty_name}`
      : transaction.description
        ? `Rule for ${transaction.description.slice(0, 50)}`
        : 'New Rule'

    ruleForm = {
      name: ruleName,
      match: 'all',
      conditions,
      is_active: true,
      priority: 0
    }
    newConditions = conditions.map(c => ({ ...c }))
    ruleMode = 'create'
    existingRules = []
    selectedExistingRuleId = ''
    ruleTargetCategoryId = transaction.category_id ? String(transaction.category_id) : ''
    show = true
    if (ruleTargetCategoryId) {
      loadExistingRules(ruleTargetCategoryId)
    }
  }

  async function loadExistingRules(categoryId) {
    if (!categoryId) {
      existingRules = []
      return
    }
    loadingExistingRules = true
    try {
      existingRules = await api.categories.rules.list(parseInt(categoryId))
    } catch (error) {
      existingRules = []
    } finally {
      loadingExistingRules = false
    }
  }

  function handleRuleCategoryChange(categoryId) {
    ruleTargetCategoryId = categoryId
    selectedExistingRuleId = ''
    loadExistingRules(categoryId)
  }

  function addRuleCondition() {
    ruleForm.conditions = [...ruleForm.conditions, { field: 'description', operator: 'contains', value: '' }]
  }

  function removeRuleCondition(index) {
    if (ruleForm.conditions.length > 1) {
      ruleForm.conditions = ruleForm.conditions.filter((_, i) => i !== index)
    }
  }

  function updateRuleConditionField(index, field) {
    const operators = operatorOptions[field]
    ruleForm.conditions[index].field = field
    ruleForm.conditions[index].operator = operators[0].value
    ruleForm.conditions[index].value = ''
  }

  async function saveRule() {
    if (ruleMode === 'create') {
      if (!ruleTargetCategoryId) {
        window.showToast?.('Please select a category', 'error')
        return
      }
      if (!ruleForm.name.trim()) {
        window.showToast?.('Rule name is required', 'error')
        return
      }
      const hasEmptyValue = ruleForm.conditions.some(c => !c.value && c.value !== 0)
      if (hasEmptyValue) {
        window.showToast?.('All conditions must have a value', 'error')
        return
      }

      savingRule = true
      try {
        await api.categories.rules.create(parseInt(ruleTargetCategoryId), {
          name: ruleForm.name.trim(),
          conditions: {
            match: ruleForm.match,
            rules: ruleForm.conditions
          },
          is_active: ruleForm.is_active,
          priority: ruleForm.priority
        })
        show = false
        window.showToast?.('Rule created successfully', 'success')
      } catch (error) {
        window.showToast?.(error.message, 'error')
      } finally {
        savingRule = false
      }
    } else {
      // Add to existing rule
      if (!selectedExistingRuleId) {
        window.showToast?.('Please select a rule', 'error')
        return
      }
      const hasEmptyValue = newConditions.some(c => !c.value && c.value !== 0)
      if (hasEmptyValue) {
        window.showToast?.('All conditions must have a value', 'error')
        return
      }

      const rule = existingRules.find(r => r.id === parseInt(selectedExistingRuleId))
      if (!rule) return

      savingRule = true
      try {
        const mergedConditions = [...rule.conditions.rules, ...newConditions]
        await api.categories.rules.update(rule.id, {
          conditions: {
            match: rule.conditions.match,
            rules: mergedConditions
          }
        })
        show = false
        window.showToast?.(`Conditions added to "${rule.name}"`, 'success')
      } catch (error) {
        window.showToast?.(error.message, 'error')
      } finally {
        savingRule = false
      }
    }
  }
</script>

<Modal bind:show title={ruleMode === 'create' ? 'Create Rule' : 'Add to Existing Rule'} size="xl">
  <div class="space-y-4">
    <!-- Mode toggle -->
    <div class="flex rounded-lg border border-va-border overflow-hidden">
      <button
        onclick={() => ruleMode = 'create'}
        class="flex-1 px-4 py-2 text-sm font-medium transition-all {ruleMode === 'create' ? 'bg-va-accent text-white' : 'bg-va-subtle text-va-muted hover:text-va-text'}"
      >
        Create New Rule
      </button>
      <button
        onclick={() => ruleMode = 'existing'}
        class="flex-1 px-4 py-2 text-sm font-medium transition-all {ruleMode === 'existing' ? 'bg-va-accent text-white' : 'bg-va-subtle text-va-muted hover:text-va-text'}"
      >
        Add to Existing Rule
      </button>
    </div>

    <!-- Category selector -->
    <div>
      <span class="block text-sm text-va-muted mb-1">Category <span class="text-va-danger">*</span></span>
      <select
        value={ruleTargetCategoryId}
        onchange={(e) => handleRuleCategoryChange(e.target.value)}
        class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
      >
        <option value="">Select a category...</option>
        {#each categories || [] as category}
          <option value={String(category.id)}>{category.name}</option>
        {/each}
      </select>
    </div>

    {#if ruleMode === 'existing'}
      <!-- Existing rule selector -->
      <div>
        <span class="block text-sm text-va-muted mb-1">Rule <span class="text-va-danger">*</span></span>
        {#if loadingExistingRules}
          <div class="flex items-center gap-2 py-2">
            <div class="w-4 h-4 border-2 border-va-muted border-t-transparent rounded-full animate-spin"></div>
            <span class="text-sm text-va-muted">Loading rules...</span>
          </div>
        {:else if !ruleTargetCategoryId}
          <p class="text-sm text-va-muted py-2">Select a category first</p>
        {:else if existingRules.length === 0}
          <p class="text-sm text-va-muted py-2">No existing rules for this category. Switch to "Create New Rule" instead.</p>
        {:else}
          <select
            bind:value={selectedExistingRuleId}
            class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
          >
            <option value="">Select a rule...</option>
            {#each existingRules as rule}
              <option value={String(rule.id)}>{rule.name}</option>
            {/each}
          </select>
        {/if}
      </div>

      <!-- Show selected rule's current conditions -->
      {#if selectedExistingRuleId}
        {@const selectedRule = existingRules.find(r => r.id === parseInt(selectedExistingRuleId))}
        {#if selectedRule}
          <div class="p-3 bg-va-hover/50 rounded-md border border-va-border/30">
            <span class="block text-xs text-va-muted mb-1">Current conditions (match {selectedRule.conditions.match === 'all' ? 'ALL' : 'ANY'}):</span>
            {#each selectedRule.conditions.rules as condition}
              <div class="text-xs text-va-muted">
                - {fieldOptions.find(f => f.value === condition.field)?.label || condition.field}
                <span class="text-va-text">{operatorOptions[condition.field]?.find(o => o.value === condition.operator)?.label || condition.operator}</span>
                "<span class="text-va-accent">{condition.value}</span>"
              </div>
            {/each}
          </div>
        {/if}
      {/if}

      <!-- Conditions to add -->
      <div>
        <span class="block text-sm text-va-muted mb-2">Conditions to Add</span>
        <div class="space-y-2">
          {#each newConditions as condition, index}
            <div class="flex flex-wrap items-center gap-2 p-3 bg-va-hover/50 rounded-md border border-va-accent/30">
              <select
                value={condition.field}
                onchange={(e) => {
                  const field = e.target.value
                  const operators = operatorOptions[field]
                  newConditions[index].field = field
                  newConditions[index].operator = operators[0].value
                  newConditions[index].value = ''
                }}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each fieldOptions as field}
                  <option value={field.value}>{field.label}</option>
                {/each}
              </select>

              <select
                bind:value={condition.operator}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each operatorOptions[condition.field] || [] as op}
                  <option value={op.value}>{op.label}</option>
                {/each}
              </select>

              {#if condition.field === 'direction'}
                <select
                  bind:value={condition.value}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                >
                  <option value="">Select...</option>
                  <option value="in">Income (positive)</option>
                  <option value="out">Expense (negative)</option>
                </select>
              {:else}
                <input
                  type={condition.field === 'amount' ? 'number' : 'text'}
                  bind:value={condition.value}
                  placeholder={condition.field === 'amount' ? '0.00' : 'Value...'}
                  step={condition.field === 'amount' ? '0.01' : undefined}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                />
              {/if}

              <button
                onclick={() => {
                  if (newConditions.length > 1) {
                    newConditions = newConditions.filter((_, i) => i !== index)
                  }
                }}
                disabled={newConditions.length <= 1}
                class="p-1.5 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                title="Remove condition"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          {/each}
        </div>

        <button
          onclick={() => newConditions = [...newConditions, { field: 'description', operator: 'contains', value: '' }]}
          class="mt-2 text-sm text-va-accent hover:text-va-accent/80"
        >
          + Add Condition
        </button>
      </div>
    {:else}
      <!-- Create new rule form -->
      <!-- Rule name -->
      <div>
        <span class="block text-sm text-va-muted mb-1">Rule Name <span class="text-va-danger">*</span></span>
        <input
          type="text"
          bind:value={ruleForm.name}
          placeholder="e.g. Salary from Company X"
          class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
        />
      </div>

      <!-- Match type -->
      <div>
        <span class="block text-sm text-va-muted mb-1">Match Conditions</span>
        <select
          bind:value={ruleForm.match}
          class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
        >
          <option value="all">ALL conditions must match (AND)</option>
          <option value="any">ANY condition can match (OR)</option>
        </select>
      </div>

      <!-- Conditions -->
      <div>
        <span class="block text-sm text-va-muted mb-2">Conditions</span>
        <div class="space-y-2">
          {#each ruleForm.conditions as condition, index}
            <div class="flex flex-wrap items-center gap-2 p-3 bg-va-hover/50 rounded-md border border-va-border/30">
              <select
                value={condition.field}
                onchange={(e) => updateRuleConditionField(index, e.target.value)}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each fieldOptions as field}
                  <option value={field.value}>{field.label}</option>
                {/each}
              </select>

              <select
                bind:value={condition.operator}
                class="px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
              >
                {#each operatorOptions[condition.field] || [] as op}
                  <option value={op.value}>{op.label}</option>
                {/each}
              </select>

              {#if condition.field === 'direction'}
                <select
                  bind:value={condition.value}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                >
                  <option value="">Select...</option>
                  <option value="in">Income (positive)</option>
                  <option value="out">Expense (negative)</option>
                </select>
              {:else}
                <input
                  type={condition.field === 'amount' ? 'number' : 'text'}
                  bind:value={condition.value}
                  placeholder={condition.field === 'amount' ? '0.00' : 'Value...'}
                  step={condition.field === 'amount' ? '0.01' : undefined}
                  class="flex-1 px-2 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                />
              {/if}

              <button
                onclick={() => removeRuleCondition(index)}
                disabled={ruleForm.conditions.length <= 1}
                class="p-1.5 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                title="Remove condition"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          {/each}
        </div>

        <button
          onclick={addRuleCondition}
          class="mt-2 text-sm text-va-accent hover:text-va-accent/80"
        >
          + Add Condition
        </button>
      </div>

      <!-- Active & Priority -->
      <div class="flex items-center gap-4">
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            bind:checked={ruleForm.is_active}
            class="rounded border-va-border text-va-accent focus:ring-va-accent"
          />
          <span class="text-sm text-va-text">Active</span>
        </label>

        <div class="flex items-center gap-2">
          <span class="text-sm text-va-muted">Priority:</span>
          <input
            type="number"
            bind:value={ruleForm.priority}
            min="0"
            class="w-16 px-2 py-1 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
          />
          <span class="text-xs text-va-muted">(lower = higher priority)</span>
        </div>
      </div>
    {/if}

    <!-- Actions -->
    <div class="flex gap-3 pt-4 border-t border-va-border">
      <button
        onclick={saveRule}
        disabled={savingRule}
        class="px-4 py-2 text-sm font-medium rounded-lg bg-va-accent text-white hover:bg-va-accent/90 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
      >
        {#if savingRule}
          <div class="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
        {/if}
        {ruleMode === 'create' ? 'Create Rule' : 'Add Conditions'}
      </button>
      <button
        onclick={() => show = false}
        class="px-4 py-2 text-sm font-medium rounded-lg border border-va-border text-va-muted hover:text-va-text hover:bg-va-hover transition-all"
      >
        Cancel
      </button>
    </div>
  </div>
</Modal>
