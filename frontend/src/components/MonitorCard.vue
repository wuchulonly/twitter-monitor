<template>
  <div class="monitor-card">
    <div class="monitor-header">
      <div class="monitor-info">
        <span class="monitor-username">@{{ monitor.twitter_username }}</span>
        <span v-if="monitor.display_name" class="monitor-display-name">{{ monitor.display_name }}</span>
      </div>
      <span :class="['tag', monitor.is_active ? 'tag-active' : 'tag-inactive']">
        {{ monitor.is_active ? $t('common.active') : $t('common.paused') }}
      </span>
    </div>
    <div class="monitor-meta mono">
      {{ $t('monitors.every_min', { n: monitor.check_interval }) }} &middot;
      {{ $t('monitors.last_check', { time: monitor.last_check ? new Date(monitor.last_check).toLocaleString('zh-CN') : $t('common.never') }) }}
    </div>
    <div class="monitor-actions">
      <button
        class="btn btn-sm"
        :class="monitor.is_active ? 'btn-danger' : 'btn-success'"
        @click="$emit('toggle-active', monitor)"
      >
        {{ monitor.is_active ? $t('monitors.pause') : $t('monitors.resume') }}
      </button>
      <button
        class="btn btn-sm btn-ghost"
        :disabled="isBackfilling || isBackfillingAll || monitor.history_complete"
        @click="$emit('backfill', monitor)"
      >
        {{ isBackfilling ? $t('monitors.backfilling_more') : $t('monitors.backfill_more') }}
      </button>
      <button
        class="btn btn-sm btn-ghost"
        :disabled="isBackfilling || isBackfillingAll || monitor.history_complete"
        @click="$emit('backfill-all', monitor)"
      >
        {{
          monitor.history_complete
            ? $t('monitors.history_complete')
            : isBackfillingAll
              ? $t('monitors.backfilling_all')
              : $t('monitors.backfill_all')
        }}
      </button>
      <button class="btn btn-sm btn-danger" @click="$emit('delete', monitor.id)">{{ $t('common.delete') }}</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  monitor: Object,
  isBackfilling: Boolean,
  isBackfillingAll: Boolean,
})
defineEmits(['toggle-active', 'backfill', 'backfill-all', 'delete'])
</script>

<style scoped>
.monitor-card {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px 20px;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.monitor-card:hover {
  border-color: var(--border-active);
  transform: translateY(-1px);
}

.monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.monitor-info {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.monitor-username {
  color: var(--accent);
  font-weight: 600;
  font-size: 15px;
}

.monitor-display-name {
  color: var(--text-secondary);
  font-size: 13px;
}

.monitor-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 12px;
}

.monitor-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
