<script setup lang="ts">
import { computed } from 'vue'
import NbPanel from './NbPanel.vue'
import NbProgress from './NbProgress.vue'
import NbStatGrid from './NbStatGrid.vue'
import NbCheckList from './NbCheckList.vue'
import type { NbCheckItem, NbStat, Tone } from './types'

export type RunPhase = 'queued' | 'running' | 'complete' | 'failed'

const props = withDefaults(
  defineProps<{
    /** e.g. "16 candidates" */
    title: string
    /** e.g. "draco-3pass" */
    benchmark?: string
    phase?: RunPhase
    /** e.g. "4M 51S" */
    elapsed?: string
    done: number
    total: number
    stats?: NbStat[]
    recent?: NbCheckItem[]
    /** e.g. "+1 MORE" */
    recentExtra?: string
    caption?: string
  }>(),
  {
    benchmark: '',
    phase: 'running',
    elapsed: '',
    stats: () => [],
    recent: () => [],
    recentExtra: '',
    caption: '',
  },
)

const PHASE: Record<RunPhase, { label: string; tone: Tone }> = {
  queued: { label: 'QUEUED', tone: 'neutral' },
  running: { label: 'RUNNING', tone: 'info' },
  complete: { label: 'COMPLETE', tone: 'accent' },
  failed: { label: 'FAILED', tone: 'danger' },
}

const phaseInfo = computed(() => PHASE[props.phase])
</script>

<template>
  <NbPanel
    bordered
    rule="none"
    :title="title"
    :subtitle="benchmark"
    :status="phaseInfo.label"
    :tone="phaseInfo.tone"
    :meta="elapsed"
    :caption="caption"
  >
    <NbProgress
      :label="phaseInfo.label.charAt(0) + phaseInfo.label.slice(1).toLowerCase()"
      :value="done"
      :total="total"
      :indeterminate="phase === 'running'"
    />
    <NbStatGrid v-if="stats.length" :stats="stats" :columns="stats.length" />
    <NbCheckList v-if="recent.length" :items="recent" label="Recent" :extra="recentExtra" />
  </NbPanel>
</template>
