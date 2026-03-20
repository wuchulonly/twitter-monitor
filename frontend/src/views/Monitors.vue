<template>
  <div>
    <h1 class="page-title page-header">{{ $t('monitors.title') }}</h1>

    <div class="card">
      <h2>{{ $t('monitors.add_monitor') }}</h2>
      <div class="monitor-form">
        <div class="form-group form-col-username">
          <label>{{ $t('monitors.twitter_username') }}</label>
          <textarea
            v-model="form.twitter_username"
            placeholder="@username"
            rows="3"
            spellcheck="false"
          />
          <p class="form-hint">{{ $t('monitors.username_hint') }}</p>
        </div>
        <div class="form-group form-col-display">
          <label>{{ $t('monitors.display_name') }}</label>
          <input v-model="form.display_name" :placeholder="$t('monitors.display_name')" />
        </div>
        <div class="form-group form-col-interval">
          <label>{{ $t('monitors.interval') }}</label>
          <input v-model.number="form.check_interval" type="number" min="3" />
        </div>
        <div class="form-group form-col-account">
          <label>{{ $t('monitors.account') }}</label>
          <select v-model="form.account_id">
            <option v-for="a in accounts" :key="a.id" :value="a.id">@{{ a.username }}</option>
          </select>
        </div>
        <div class="form-col-action">
          <button class="btn btn-primary" @click="addMonitor">{{ $t('common.add') }}</button>
        </div>
      </div>
      <p v-if="success" class="form-success">{{ success }}</p>
      <p v-if="error" class="form-error">{{ error }}</p>
    </div>

    <div class="grid monitor-grid">
      <MonitorCard
        v-for="m in monitors"
        :key="m.id"
        :monitor="m"
        :is-backfilling="backfillJob.id === m.id && !backfillJob.untilEnd"
        :is-backfilling-all="backfillJob.id === m.id && backfillJob.untilEnd"
        @toggle-active="toggleActive"
        @backfill="backfillOlderTweets"
        @backfill-all="backfillAllTweets"
        @delete="remove"
      />
    </div>

    <div v-if="!monitors.length" class="card empty-state">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
      <p>{{ $t('monitors.no_monitors') }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  backfillMonitor,
  createMonitor,
  createMonitorsBulk,
  deleteMonitor,
  getAccounts,
  getMonitors,
  updateMonitor,
} from '../api/index.js'
import MonitorCard from '../components/MonitorCard.vue'

const { t } = useI18n()
const accounts = ref([])
const monitors = ref([])
const error = ref('')
const success = ref('')
const backfillJob = ref({ id: null, untilEnd: false })
const form = ref({ twitter_username: '', display_name: '', check_interval: 5, account_id: null })

function normalizeUsername(value) {
  return value.trim().replace(/^@+/, '').trim()
}

function parseUsernames(value) {
  return value
    .split(/[\n,，]+/)
    .map(normalizeUsername)
    .filter(Boolean)
}

function mapError(detail) {
  if (detail && (detail.includes('429') || detail.toLowerCase().includes('rate limit'))) {
    return t('monitors.backfill_rate_limited')
  }
  const knownErrors = {
    'Already monitoring this user': t('monitors.already_monitoring'),
    'Duplicate username in request': t('monitors.duplicate_in_request'),
    'Twitter username is required': t('monitors.username_required'),
    'Twitter account not found': t('monitors.login_first'),
  }
  return knownErrors[detail] || detail || t('monitors.add_failed')
}

function buildBulkIssues(items) {
  return items
    .map((item) => {
      const prefix = item.twitter_username ? `@${item.twitter_username}: ` : ''
      return `${prefix}${mapError(item.detail)}`
    })
    .join('；')
}

async function load() {
  const [a, m] = await Promise.all([getAccounts(), getMonitors()])
  accounts.value = a.data
  monitors.value = m.data
  if (!form.value.account_id && a.data.length) form.value.account_id = a.data[0].id
}

async function addMonitor() {
  error.value = ''
  success.value = ''
  const usernames = parseUsernames(form.value.twitter_username)
  if (!usernames.length) { error.value = t('monitors.username_required'); return }
  if (!form.value.account_id) { error.value = t('monitors.login_first'); return }
  try {
    if (usernames.length === 1) {
      await createMonitor({
        twitter_username: usernames[0],
        display_name: form.value.display_name.trim() || undefined,
        check_interval: form.value.check_interval,
        account_id: form.value.account_id,
      })
      success.value = t('monitors.single_success', { username: `@${usernames[0]}` })
    } else {
      const { data } = await createMonitorsBulk({
        input_text: form.value.twitter_username,
        check_interval: form.value.check_interval,
        account_id: form.value.account_id,
      })
      if (data.summary.created) {
        success.value = t('monitors.batch_success', {
          created: data.summary.created,
          total: data.summary.total_requested,
        })
      }
      const issues = [...data.skipped, ...data.failed]
      if (issues.length) {
        error.value = buildBulkIssues(issues)
      }
    }
    form.value.twitter_username = ''
    form.value.display_name = ''
    await load()
  } catch (e) {
    error.value = mapError(e.response?.data?.detail)
  }
}

async function toggleActive(m) {
  await updateMonitor(m.id, { is_active: !m.is_active })
  await load()
}

async function remove(id) {
  if (!confirm(t('common.confirm_delete'))) return
  await deleteMonitor(id)
  await load()
}

async function runBackfill(monitor, untilEnd = false) {
  error.value = ''
  success.value = ''
  backfillJob.value = { id: monitor.id, untilEnd }
  try {
    const { data } = await backfillMonitor(monitor.id, {
      batch_size: 100,
      until_end: untilEnd,
    })
    success.value = t(
      untilEnd ? 'monitors.backfill_all_success' : 'monitors.backfill_success',
      {
        username: `@${monitor.twitter_username}`,
        count: data.new_tweets,
        total: data.stored_count,
        pages: data.pages_fetched,
      },
    )
    if (untilEnd && data.reached_end) {
      success.value += ` ${t('monitors.backfill_reached_end')}`
    }
    await load()
  } catch (e) {
    error.value = mapError(e.response?.data?.detail) || t('monitors.backfill_failed')
  } finally {
    backfillJob.value = { id: null, untilEnd: false }
  }
}

async function backfillOlderTweets(monitor) {
  await runBackfill(monitor, false)
}

async function backfillAllTweets(monitor) {
  if (!confirm(t('monitors.backfill_all_confirm', { username: `@${monitor.twitter_username}` }))) return
  await runBackfill(monitor, true)
}

onMounted(load)
</script>

<style scoped>
.monitor-form {
  display: grid;
  grid-template-columns: 1fr 1fr 100px 160px auto;
  gap: 12px;
  align-items: end;
}

.form-hint {
  margin-top: 6px;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.5;
}

.form-col-username textarea {
  min-height: 92px;
  resize: vertical;
  font-family: inherit;
}

.form-col-action {
  padding-bottom: 16px;
}

.monitor-grid {
  margin-top: 0;
}

@media (max-width: 768px) {
  .monitor-form {
    grid-template-columns: 1fr;
  }
  .form-col-action {
    padding-bottom: 0;
  }
}
</style>
