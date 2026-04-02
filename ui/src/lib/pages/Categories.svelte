<script>
  import { onMount } from 'svelte'
  import Card from '../components/Card.svelte'
  import Button from '../components/Button.svelte'
  import Modal from '../components/Modal.svelte'
  import Input from '../components/Input.svelte'
  import api from '../api.js'

  let categories = $state([])
  let loading = $state(true)
  let showCreateModal = $state(false)
  let creating = $state(false)
  let editingCategory = $state(null)
  let saving = $state(false)

  // Rule state
  let expandedCategoryId = $state(null)
  let categoryRules = $state({}) // { categoryId: [rules] }
  let loadingRules = $state({}) // { categoryId: boolean }
  let showRuleModal = $state(false)
  let editingRule = $state(null)
  let savingRule = $state(false)

  // Rule form
  let ruleForm = $state({
    name: '',
    match: 'all',
    conditions: [{ field: 'description', operator: 'contains', value: '' }],
    is_active: true,
    priority: 0
  })

  // Field and operator options
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

  // Form state for create
  let form = $state({
    name: '',
    description: '',
    color: '#6366f1'
  })

  // Predefined colors
  const colorOptions = [
    '#6366f1', // indigo
    '#8b5cf6', // violet
    '#ec4899', // pink
    '#ef4444', // red
    '#f97316', // orange
    '#eab308', // yellow
    '#22c55e', // green
    '#14b8a6', // teal
    '#0ea5e9', // sky
    '#3b82f6', // blue
  ]

  onMount(async () => {
    await loadCategories()
  })

  async function loadCategories() {
    loading = true
    try {
      categories = await api.categories.list()
    } catch (error) {
      console.error('Failed to load categories:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      loading = false
    }
  }

  async function loadRules(categoryId) {
    if (categoryRules[categoryId]) return // Already loaded
    
    loadingRules[categoryId] = true
    try {
      const rules = await api.categories.rules.list(categoryId)
      categoryRules[categoryId] = rules
    } catch (error) {
      console.error('Failed to load rules:', error)
      window.showToast?.(error.message, 'error')
    } finally {
      loadingRules[categoryId] = false
    }
  }

  function toggleExpanded(categoryId) {
    if (expandedCategoryId === categoryId) {
      expandedCategoryId = null
    } else {
      expandedCategoryId = categoryId
      loadRules(categoryId)
    }
  }

  async function createCategory() {
    if (!form.name.trim()) {
      window.showToast?.('Category name is required', 'error')
      return
    }

    creating = true
    try {
      await api.categories.create({
        name: form.name.trim(),
        description: form.description.trim() || null,
        color: form.color
      })
      showCreateModal = false
      resetForm()
      await loadCategories()
      window.showToast?.('Category created successfully', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      creating = false
    }
  }

  function resetForm() {
    form = {
      name: '',
      description: '',
      color: '#6366f1'
    }
  }

  function startEditing(category) {
    editingCategory = {
      ...category,
      originalName: category.name
    }
  }

  function cancelEditing() {
    editingCategory = null
  }

  async function saveCategory() {
    if (!editingCategory.name.trim()) {
      window.showToast?.('Category name is required', 'error')
      return
    }

    saving = true
    try {
      await api.categories.update(editingCategory.id, {
        name: editingCategory.name.trim(),
        description: editingCategory.description?.trim() || null,
        color: editingCategory.color
      })
      editingCategory = null
      await loadCategories()
      window.showToast?.('Category updated', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      saving = false
    }
  }

  async function deleteCategory(category) {
    const confirmed = confirm(`Delete category "${category.name}"?\n\nThis will remove the category from all transactions that use it.`)
    if (!confirmed) return

    try {
      const result = await api.categories.delete(category.id)
      await loadCategories()
      if (result.affected_transactions > 0) {
        window.showToast?.(`Category deleted. ${result.affected_transactions} transaction(s) updated.`, 'success')
      } else {
        window.showToast?.('Category deleted', 'success')
      }
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  // Rule functions
  function openRuleModal(categoryId, rule = null) {
    editingRule = rule ? { ...rule, categoryId } : { categoryId }
    if (rule) {
      ruleForm = {
        name: rule.name,
        match: rule.conditions.match,
        conditions: [...rule.conditions.rules],
        is_active: rule.is_active,
        priority: rule.priority
      }
    } else {
      ruleForm = {
        name: '',
        match: 'all',
        conditions: [{ field: 'description', operator: 'contains', value: '' }],
        is_active: true,
        priority: 0
      }
    }
    showRuleModal = true
  }

  function closeRuleModal() {
    showRuleModal = false
    editingRule = null
  }

  function addCondition() {
    ruleForm.conditions = [...ruleForm.conditions, { field: 'description', operator: 'contains', value: '' }]
  }

  function removeCondition(index) {
    if (ruleForm.conditions.length > 1) {
      ruleForm.conditions = ruleForm.conditions.filter((_, i) => i !== index)
    }
  }

  function updateConditionField(index, field) {
    const operators = operatorOptions[field]
    ruleForm.conditions[index].field = field
    ruleForm.conditions[index].operator = operators[0].value
    ruleForm.conditions[index].value = ''
  }

  async function saveRule() {
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
      const data = {
        name: ruleForm.name.trim(),
        conditions: {
          match: ruleForm.match,
          rules: ruleForm.conditions
        },
        is_active: ruleForm.is_active,
        priority: ruleForm.priority
      }

      if (editingRule.id) {
        await api.categories.rules.update(editingRule.id, data)
        window.showToast?.('Rule updated', 'success')
      } else {
        await api.categories.rules.create(editingRule.categoryId, data)
        window.showToast?.('Rule created', 'success')
      }

      // Reload rules for this category
      categoryRules[editingRule.categoryId] = await api.categories.rules.list(editingRule.categoryId)
      closeRuleModal()
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      savingRule = false
    }
  }

  async function deleteRule(rule, categoryId) {
    const confirmed = confirm(`Delete rule "${rule.name}"?`)
    if (!confirmed) return

    try {
      await api.categories.rules.delete(rule.id)
      categoryRules[categoryId] = categoryRules[categoryId].filter(r => r.id !== rule.id)
      window.showToast?.('Rule deleted', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  async function toggleRuleActive(rule, categoryId) {
    try {
      await api.categories.rules.update(rule.id, { is_active: !rule.is_active })
      // Update local state
      categoryRules[categoryId] = categoryRules[categoryId].map(r => 
        r.id === rule.id ? { ...r, is_active: !r.is_active } : r
      )
    } catch (error) {
      window.showToast?.(error.message, 'error')
    }
  }

  function getFieldLabel(field) {
    return fieldOptions.find(f => f.value === field)?.label || field
  }

  function getOperatorLabel(field, operator) {
    return operatorOptions[field]?.find(o => o.value === operator)?.label || operator
  }

  // Import/Export
  let exporting = $state(false)
  let importing = $state(false)

  async function exportCategories() {
    exporting = true
    try {
      const data = await api.categories.export()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `categories-export-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      window.showToast?.('Categories exported', 'success')
    } catch (error) {
      window.showToast?.(error.message, 'error')
    } finally {
      exporting = false
    }
  }

  function triggerImport() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async (e) => {
      const file = e.target.files[0]
      if (!file) return

      const confirmed = confirm(
        'Importing will replace ALL existing categories and rules.\n\nThis cannot be undone. Continue?'
      )
      if (!confirmed) return

      importing = true
      try {
        const text = await file.text()
        const data = JSON.parse(text)
        const result = await api.categories.import(data)
        categoryRules = {}
        expandedCategoryId = null
        await loadCategories()
        window.showToast?.(
          `Imported ${result.imported_categories} categories and ${result.imported_rules} rules`,
          'success'
        )
      } catch (error) {
        if (error instanceof SyntaxError) {
          window.showToast?.('Invalid JSON file', 'error')
        } else {
          window.showToast?.(error.message, 'error')
        }
      } finally {
        importing = false
      }
    }
    input.click()
  }
</script>

<div>
  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
    <h1 class="text-lg font-semibold text-va-text">Categories</h1>
    <div class="flex items-center gap-2 flex-wrap">
      <button
        onclick={triggerImport}
        disabled={importing}
        class="flex items-center gap-1.5 px-3 py-1.5 text-sm text-va-muted hover:text-va-text border border-va-border rounded-lg hover:bg-va-hover transition-all disabled:opacity-50"
        title="Import categories and rules from JSON"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        {importing ? 'Importing...' : 'Import'}
      </button>
      <button
        onclick={exportCategories}
        disabled={exporting || categories.length === 0}
        class="flex items-center gap-1.5 px-3 py-1.5 text-sm text-va-muted hover:text-va-text border border-va-border rounded-lg hover:bg-va-hover transition-all disabled:opacity-50"
        title="Export all categories and rules as JSON"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
        {exporting ? 'Exporting...' : 'Export'}
      </button>
      <Button onclick={() => showCreateModal = true}>
        New Category
      </Button>
    </div>
  </div>

  <Card>
    {#if loading}
      <div class="flex items-center justify-center h-24">
        <div class="w-6 h-6 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    {:else if categories.length === 0}
      <div class="text-center py-8">
        <div class="text-4xl mb-3">🏷️</div>
        <p class="text-va-muted text-sm">No categories yet</p>
        <p class="text-va-muted text-sm mt-1">Create categories to organize your transactions</p>
      </div>
    {:else}
      <div class="space-y-2">
        {#each categories as category}
          <div class="bg-va-hover/50 rounded-lg border border-va-border/30 hover:border-va-border transition-all">
            <div class="flex items-center justify-between p-4">
              {#if editingCategory?.id === category.id}
                <!-- Editing mode -->
                <div class="flex-1 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                  <div class="flex gap-1 flex-wrap">
                    {#each colorOptions as color}
                      <button
                        onclick={() => editingCategory.color = color}
                        class="w-6 h-6 rounded-full border-2 transition-transform hover:scale-110"
                        style="background-color: {color}; border-color: {editingCategory.color === color ? 'white' : color}"
                        class:ring-2={editingCategory.color === color}
                        class:ring-white={editingCategory.color === color}
                        class:ring-offset-2={editingCategory.color === color}
                        class:ring-offset-va-canvas={editingCategory.color === color}
                        aria-label="Select color {color}"
                      ></button>
                    {/each}
                  </div>
                  <input
                    type="text"
                    bind:value={editingCategory.name}
                    class="flex-1 px-3 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                    placeholder="Category name"
                  />
                  <input
                    type="text"
                    bind:value={editingCategory.description}
                    class="flex-1 px-3 py-1.5 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
                    placeholder="Description (optional)"
                  />
                </div>
                <div class="flex items-center gap-2 sm:ml-4">
                  <button
                    onclick={saveCategory}
                    disabled={saving}
                    class="p-2 text-va-success hover:bg-va-success/10 rounded-lg transition-all disabled:opacity-50"
                    title="Save changes"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                    </svg>
                  </button>
                  <button
                    onclick={cancelEditing}
                    class="p-2 text-va-muted hover:text-va-text hover:bg-va-hover rounded-lg transition-all"
                    title="Cancel editing"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              {:else}
                <!-- Display mode -->
                <button 
                  onclick={() => toggleExpanded(category.id)}
                  class="flex items-center gap-3 flex-1 text-left"
                >
                  <svg 
                    class="w-4 h-4 text-va-muted transition-transform {expandedCategoryId === category.id ? 'rotate-90' : ''}" 
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                  </svg>
                  <div
                    class="w-4 h-4 rounded-full shrink-0"
                    style="background-color: {category.color || '#6366f1'}"
                  ></div>
                  <div>
                    <div class="text-sm text-va-text font-medium">{category.name}</div>
                    {#if category.description}
                      <div class="text-xs text-va-muted mt-0.5">{category.description}</div>
                    {/if}
                  </div>
                </button>
                <div class="flex items-center gap-2">
                  <button
                    onclick={() => openRuleModal(category.id)}
                    class="p-2 text-va-muted hover:text-va-accent hover:bg-va-accent/10 rounded-lg transition-all"
                    title="Add rule"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                    </svg>
                  </button>
                  <button
                    onclick={() => startEditing(category)}
                    class="p-2 text-va-muted hover:text-va-accent hover:bg-va-accent/10 rounded-lg transition-all"
                    title="Edit category"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button
                    onclick={() => deleteCategory(category)}
                    class="p-2 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded-lg transition-all"
                    title="Delete category"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              {/if}
            </div>

            <!-- Expanded Rules Section -->
            {#if expandedCategoryId === category.id}
              <div class="border-t border-va-border/30 p-4 bg-va-canvas/50">
                <div class="flex items-center justify-between mb-3">
                  <h3 class="text-sm font-medium text-va-muted">Auto-categorization Rules</h3>
                  <button
                    onclick={() => openRuleModal(category.id)}
                    class="text-xs text-va-accent hover:text-va-accent/80"
                  >
                    + Add Rule
                  </button>
                </div>

                {#if loadingRules[category.id]}
                  <div class="flex items-center justify-center py-4">
                    <div class="w-4 h-4 border-2 border-va-accent border-t-transparent rounded-full animate-spin"></div>
                  </div>
                {:else if !categoryRules[category.id] || categoryRules[category.id].length === 0}
                  <p class="text-xs text-va-muted text-center py-4">
                    No rules yet. Add a rule to automatically categorize transactions.
                  </p>
                {:else}
                  <div class="space-y-2">
                    {#each categoryRules[category.id] as rule}
                      <div class="flex items-start justify-between p-3 bg-va-hover/50 rounded-md border border-va-border/30 {!rule.is_active ? 'opacity-50' : ''}">
                        <div class="flex-1">
                          <div class="flex items-center gap-2">
                            <span class="text-sm text-va-text font-medium">{rule.name}</span>
                            {#if !rule.is_active}
                              <span class="text-xs px-1.5 py-0.5 bg-va-muted/20 rounded text-va-muted">Disabled</span>
                            {/if}
                          </div>
                          <div class="text-xs text-va-muted mt-1">
                            Match <span class="font-medium">{rule.conditions.match === 'all' ? 'ALL' : 'ANY'}</span> of:
                          </div>
                          <div class="mt-1 space-y-0.5">
                            {#each rule.conditions.rules as condition}
                              <div class="text-xs text-va-muted pl-2">
                                - {getFieldLabel(condition.field)} <span class="text-va-text">{getOperatorLabel(condition.field, condition.operator)}</span> "<span class="text-va-accent">{condition.value}</span>"
                              </div>
                            {/each}
                          </div>
                        </div>
                        <div class="flex items-center gap-1 ml-2">
                          <button
                            onclick={() => toggleRuleActive(rule, category.id)}
                            class="p-1.5 text-va-muted hover:text-va-text hover:bg-va-hover rounded transition-all"
                            title={rule.is_active ? 'Disable rule' : 'Enable rule'}
                          >
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              {#if rule.is_active}
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                              {:else}
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                              {/if}
                            </svg>
                          </button>
                          <button
                            onclick={() => openRuleModal(category.id, rule)}
                            class="p-1.5 text-va-muted hover:text-va-accent hover:bg-va-accent/10 rounded transition-all"
                            title="Edit rule"
                          >
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                            </svg>
                          </button>
                          <button
                            onclick={() => deleteRule(rule, category.id)}
                            class="p-1.5 text-va-muted hover:text-va-danger hover:bg-va-danger/10 rounded transition-all"
                            title="Delete rule"
                          >
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </Card>
</div>

<!-- Create Category Modal -->
<Modal bind:show={showCreateModal} title="New Category" onClose={resetForm}>
  <Input
    label="Name"
    bind:value={form.name}
    placeholder="e.g. Office Supplies, Travel, Marketing"
    required
  />

  <Input
    label="Description"
    bind:value={form.description}
    placeholder="Optional description"
  />

  <div>
    <span class="block text-sm text-va-muted mb-2">Color</span>
    <div class="flex gap-2 flex-wrap">
      {#each colorOptions as color}
        <button
          onclick={() => form.color = color}
          class="w-8 h-8 rounded-full border-2 transition-transform hover:scale-110"
          style="background-color: {color}; border-color: {form.color === color ? 'white' : color}"
          class:ring-2={form.color === color}
          class:ring-white={form.color === color}
          class:ring-offset-2={form.color === color}
          class:ring-offset-va-canvas={form.color === color}
          aria-label="Select color {color}"
        ></button>
      {/each}
    </div>
  </div>

  <div class="flex gap-3 mt-5 pt-4 border-t border-va-border">
    <Button onclick={createCategory} loading={creating}>
      Create Category
    </Button>
    <Button variant="secondary" onclick={() => showCreateModal = false}>
      Cancel
    </Button>
  </div>
</Modal>

<!-- Rule Modal -->
<Modal bind:show={showRuleModal} title={editingRule?.id ? 'Edit Rule' : 'New Rule'} size="xl" onClose={closeRuleModal}>
  <Input
    label="Rule Name"
    bind:value={ruleForm.name}
    placeholder="e.g. Salary from Company X"
    required
  />

  <div>
    <span class="block text-sm text-va-muted mb-2">Match Conditions</span>
    <select
      bind:value={ruleForm.match}
      class="w-full px-3 py-2 text-sm bg-va-canvas border border-va-border rounded-md text-va-text focus:outline-none focus:ring-1 focus:ring-va-accent"
    >
      <option value="all">ALL conditions must match (AND)</option>
      <option value="any">ANY condition can match (OR)</option>
    </select>
  </div>

  <div>
    <span class="block text-sm text-va-muted mb-2">Conditions</span>
    <div class="space-y-2">
      {#each ruleForm.conditions as condition, index}
        <div class="flex flex-wrap items-center gap-2 p-3 bg-va-hover/50 rounded-md border border-va-border/30">
          <select
            value={condition.field}
            onchange={(e) => updateConditionField(index, e.target.value)}
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
            onclick={() => removeCondition(index)}
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
      onclick={addCondition}
      class="mt-2 text-sm text-va-accent hover:text-va-accent/80"
    >
      + Add Condition
    </button>
  </div>

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

  <div class="flex gap-3 mt-5 pt-4 border-t border-va-border">
    <Button onclick={saveRule} loading={savingRule}>
      {editingRule?.id ? 'Save Changes' : 'Create Rule'}
    </Button>
    <Button variant="secondary" onclick={closeRuleModal}>
      Cancel
    </Button>
  </div>
</Modal>
