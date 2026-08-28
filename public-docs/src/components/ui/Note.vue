<script setup lang="ts">
/**
 * An inline callout for something a reader needs *before* they trip over it.
 * The pattern is borrowed from the Syft docs, which repeat this markup per use;
 * here it is a component so the styling stays in one place.
 */
withDefaults(defineProps<{ label?: string }>(), { label: 'Note:' })
</script>

<template>
  <div class="note not-prose my-6 p-4 rounded-lg bg-amber-500/10 border border-amber-500/30">
    <p class="text-sm text-foreground">
      <span class="text-amber-500 font-semibold">{{ label }}</span>
      <slot />
    </p>
  </div>
</template>

<style scoped>
/* WHY: the callout is `.not-prose`, so Tailwind Typography's link styling never reaches inside
   it — links rendered as plain body copy, indistinguishable from the text around them. Restore
   the affordance with the same token prose uses for links (`--accent-text-low`, which flips
   with the theme), and underline it so colour is not the only signal. `:deep()` is required
   because the links live in slot content, which belongs to the parent's scope. */
.note :deep(a) {
  color: var(--accent-text-low);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.note :deep(a:hover) {
  color: var(--accent-text-high);
}
</style>
