<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">{{ $t('dashboard.title') }}</h1>
        <div class="status-indicator">
          <span class="status-pulse"></span>
          <span class="status-label">{{ $t('status.monitoring') }}</span>
        </div>
      </div>
      <button class="btn btn-ghost" @click="checkNow" :disabled="checking">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
        {{ checking ? $t('dashboard.checking') : $t('dashboard.check_now') }}
      </button>
    </div>

    <p v-if="checkError" class="form-error">{{ checkError }}</p>
    <p v-else-if="checkMessage" class="form-success">{{ checkMessage }}</p>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
        </div>
        <div class="stat-value mono">{{ accounts.length }}</div>
        <div class="stat-label">{{ $t('dashboard.accounts') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </div>
        <div class="stat-value mono">{{ monitors.length }}</div>
        <div class="stat-label">{{ $t('dashboard.monitors') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <div class="stat-value mono">{{ tweets.length }}</div>
        <div class="stat-label">{{ $t('dashboard.tweets') }}</div>
      </div>
    </div>

    <div class="card">
      <h2>{{ $t('dashboard.latest_tweets') }}</h2>
      <div v-if="!tweets.length" class="empty-state">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <p>{{ $t('dashboard.no_tweets') }}</p>
      </div>
      <TweetCard v-for="t in tweets" :key="t.id" :tweet="t" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAccounts, getMonitors, getTweets, triggerCheck } from '../api/index.js'
import TweetCard from '../components/TweetCard.vue'

const { t } = useI18n()
const accounts = ref([])
const monitors = ref([])
const tweets = ref([])
const checking = ref(false)
const checkError = ref('')
const checkMessage = ref('')

async function load() {
  const [a, m, t] = await Promise.all([getAccounts(), getMonitors(), getTweets({ size: 10 })])
  accounts.value = a.data
  monitors.value = m.data
  tweets.value = t.data
}

async function checkNow() {
  checking.value = true
  checkError.value = ''
  checkMessage.value = ''
  try {
    const { data } = await triggerCheck()
    await load()
    const failures = data.summary?.failures?.length || 0
    if (failures) {
      checkError.value = t('dashboard.check_partial', { count: failures })
      return
    }
    checkMessage.value = t('dashboard.check_success', {
      tweets: data.summary?.new_tweets ?? 0,
      notified: data.summary?.notified_tweets ?? 0,
    })
  } catch (e) {
    checkError.value = e.response?.data?.detail || t('dashboard.check_failed')
  } finally {
    checking.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
  animation: pulse 2s ease-in-out infinite;
}

.status-label {
  font-size: 12px;
  color: var(--text-tertiary);
  font-weight: 500;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-top: 2px solid var(--accent);
  border-radius: var(--radius-md);
  padding: 20px;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.stat-card:hover {
  border-color: var(--border-active);
  border-top-color: var(--accent);
  transform: translateY(-1px);
}

.stat-icon {
  color: var(--accent);
  margin-bottom: 12px;
  opacity: 0.7;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 500;
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
  .page-header-left {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
}
</style>
