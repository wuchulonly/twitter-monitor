<template>
  <div>
    <h1 class="page-title page-header">{{ $t('settings.title') }}</h1>

    <div class="card settings-card">
      <h2>{{ $t('settings.add_channel') }}</h2>

      <div class="form-group">
        <label>{{ $t('settings.channel_type') }}</label>
        <div class="segment-control">
          <button
            :class="['segment-btn', form.channel_type === 'enterprise_wechat' && 'segment-btn--active']"
            @click="form.channel_type = 'enterprise_wechat'"
          >
            {{ $t('settings.enterprise_wechat') }}
          </button>
          <button
            :class="['segment-btn', form.channel_type === 'serverchan' && 'segment-btn--active']"
            @click="form.channel_type = 'serverchan'"
          >
            {{ $t('settings.serverchan') }}
          </button>
          <button
            :class="['segment-btn', form.channel_type === 'dingtalk' && 'segment-btn--active']"
            @click="form.channel_type = 'dingtalk'"
          >
            {{ $t('settings.dingtalk') }}
          </button>
        </div>
      </div>

      <div class="form-group">
        <label>{{ $t('settings.channel_name') }}</label>
        <input v-model="form.name" :placeholder="$t('settings.channel_name_placeholder')" />
      </div>
      <div v-if="form.channel_type === 'enterprise_wechat'" class="form-group">
        <label>{{ $t('settings.webhook_url') }}</label>
        <input v-model="form.webhook_url" :placeholder="$t('settings.webhook_placeholder')" />
      </div>
      <div v-if="form.channel_type === 'serverchan'" class="form-group">
        <label>{{ $t('settings.send_key') }}</label>
        <input v-model="form.send_key" :placeholder="$t('settings.send_key_placeholder')" />
      </div>
      <div v-if="form.channel_type === 'dingtalk'" class="form-group">
        <label>{{ $t('settings.webhook_url') }}</label>
        <input v-model="form.webhook_url" :placeholder="$t('settings.dingtalk_webhook_placeholder')" />
      </div>
      <div v-if="form.channel_type === 'dingtalk'" class="form-group">
        <label>{{ $t('settings.secret_optional') }}</label>
        <input v-model="form.send_key" :placeholder="$t('settings.dingtalk_secret_placeholder')" />
      </div>
      <button class="btn btn-primary" @click="addChannel">{{ $t('common.add') }}</button>
      <p v-if="error" class="form-error">{{ error }}</p>
    </div>

    <div class="card">
      <h2>{{ $t('settings.configured_channels') }}</h2>
      <div v-if="!channels.length" class="empty-state-inline">{{ $t('settings.no_channels') }}</div>
      <div v-for="ch in channels" :key="ch.id" class="channel-row">
        <div class="channel-info">
          <strong class="channel-name">{{ ch.name }}</strong>
          <span class="tag tag-info">
            {{ channelTypeLabel(ch.channel_type) }}
          </span>
          <span :class="['tag', ch.is_active ? 'tag-active' : 'tag-inactive']">
            {{ ch.is_active ? $t('common.active') : $t('common.inactive') }}
          </span>
        </div>
        <div class="channel-actions">
          <button class="btn btn-sm btn-ghost" @click="test(ch.id)" :disabled="testing === ch.id">
            {{ testing === ch.id ? $t('settings.testing') : $t('common.test') }}
          </button>
          <button class="btn btn-sm btn-danger" @click="remove(ch.id)">{{ $t('common.delete') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getChannels, createChannel, deleteChannel, testChannel } from '../api/index.js'

const { t } = useI18n()
const channels = ref([])
const form = ref(emptyForm())
const error = ref('')
const testing = ref(null)

function emptyForm() {
  return { channel_type: 'enterprise_wechat', name: '', webhook_url: '', send_key: '' }
}

function channelTypeLabel(channelType) {
  if (channelType === 'enterprise_wechat') return t('settings.enterprise_wechat')
  if (channelType === 'serverchan') return t('settings.serverchan')
  if (channelType === 'dingtalk') return t('settings.dingtalk')
  return channelType
}

async function load() {
  const { data } = await getChannels()
  channels.value = data
}

async function addChannel() {
  error.value = ''
  if (!form.value.name) { error.value = t('settings.name_required'); return }
  if (form.value.channel_type === 'enterprise_wechat' && !form.value.webhook_url.trim()) {
    error.value = t('settings.webhook_required')
    return
  }
  if (form.value.channel_type === 'dingtalk' && !form.value.webhook_url.trim()) {
    error.value = t('settings.webhook_required')
    return
  }
  if (form.value.channel_type === 'serverchan' && !form.value.send_key.trim()) {
    error.value = t('settings.send_key_required')
    return
  }
  try {
    const payload = {
      channel_type: form.value.channel_type,
      name: form.value.name.trim(),
      webhook_url: '',
      send_key: '',
    }

    if (form.value.channel_type === 'enterprise_wechat') {
      payload.webhook_url = form.value.webhook_url.trim()
    } else if (form.value.channel_type === 'serverchan') {
      payload.send_key = form.value.send_key.trim()
    } else if (form.value.channel_type === 'dingtalk') {
      payload.webhook_url = form.value.webhook_url.trim()
      payload.send_key = form.value.send_key.trim()
    }

    await createChannel(payload)
    form.value = emptyForm()
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || t('settings.add_failed')
  }
}

async function test(id) {
  testing.value = id
  try {
    await testChannel(id)
    alert(t('settings.test_success'))
  } catch (e) {
    alert(t('settings.test_failed', { error: e.response?.data?.detail || 'Unknown error' }))
  } finally {
    testing.value = null
  }
}

async function remove(id) {
  if (!confirm(t('common.confirm_delete'))) return
  await deleteChannel(id)
  await load()
}

onMounted(load)
</script>

<style scoped>
.settings-card {
  max-width: 500px;
}

.segment-control {
  display: flex;
  background: var(--bg-secondary);
  border-radius: var(--radius-sm);
  padding: 3px;
  gap: 2px;
}

.segment-btn {
  padding: 7px 16px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  transition: all 0.15s ease;
  flex: 1;
  text-align: center;
}
.segment-btn:hover {
  color: var(--text-primary);
}
.segment-btn--active {
  background: var(--bg-elevated);
  color: var(--accent);
  box-shadow: var(--shadow-sm);
}

.empty-state-inline {
  color: var(--text-tertiary);
  font-size: 14px;
  padding: 8px 0;
}

.channel-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  gap: 12px;
}
.channel-row:last-child { border-bottom: none; }

.channel-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.channel-name {
  color: var(--text-primary);
  font-weight: 600;
}

.channel-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .channel-row {
    flex-direction: column;
    align-items: flex-start;
  }
  .channel-actions {
    width: 100%;
  }
}
</style>
