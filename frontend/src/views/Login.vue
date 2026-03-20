<template>
  <div>
    <h1 class="page-title page-header">{{ $t('login.title') }}</h1>

    <div class="card cookie-import-card">
      <h2>{{ $t('login.import_title') }}</h2>
      <form @submit.prevent="doImportCookies">
        <div class="form-group">
          <label>{{ $t('login.email') }}</label>
          <input
            v-model="importForm.email"
            type="email"
            :placeholder="$t('login.email_placeholder')"
            autocomplete="email"
          />
          <p class="form-hint">{{ $t('login.import_email_hint') }}</p>
        </div>
        <div class="form-group">
          <label>{{ $t('login.cookie_text') }}</label>
          <textarea
            v-model="importForm.cookies"
            :placeholder="$t('login.cookie_text_placeholder')"
            rows="8"
            spellcheck="false"
          />
          <p class="form-hint">{{ $t('login.import_hint') }}</p>
        </div>

        <button class="btn btn-primary btn-full" type="submit" :disabled="importLoading">
          {{ importLoading ? $t('login.importing') : $t('login.import_button') }}
        </button>
        <p v-if="importError" class="form-error">{{ importError }}</p>
        <p v-if="importSuccess" class="form-success">{{ importSuccess }}</p>
      </form>
    </div>

    <div class="card">
      <h2>{{ $t('login.saved_accounts') }}</h2>
      <div v-if="!accounts.length" class="empty-state-inline">{{ $t('login.no_accounts') }}</div>
      <div v-for="a in accounts" :key="a.id" class="account-row">
        <div class="account-info">
          <strong class="account-username">@{{ a.username }}</strong>
          <span class="account-email">{{ a.email }}</span>
          <span :class="['tag', a.has_cookies ? 'tag-active' : 'tag-inactive']">
            {{ a.has_cookies ? $t('login.cookie_valid') : $t('login.no_cookie') }}
          </span>
        </div>
        <div class="account-actions">
          <span v-if="a.last_login" class="account-meta mono">
            {{ new Date(a.last_login).toLocaleString('zh-CN') }}
          </span>
          <button class="btn btn-sm btn-danger" @click="remove(a.id)">{{ $t('common.delete') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { importCookies, getAccounts, deleteAccount } from '../api/index.js'

const { t } = useI18n()
const accounts = ref([])
const importForm = ref({
  email: '',
  cookies: '',
})
const importLoading = ref(false)
const importError = ref('')
const importSuccess = ref('')

async function loadAccounts() {
  const { data } = await getAccounts()
  accounts.value = data
}

async function doImportCookies() {
  importError.value = ''
  importSuccess.value = ''
  importLoading.value = true
  try {
    const payload = {
      cookies: importForm.value.cookies.trim(),
      email: importForm.value.email.trim() || undefined,
    }
    const { data } = await importCookies(payload)
    importSuccess.value = data.message || t('login.import_success')
    importForm.value.email = ''
    importForm.value.cookies = ''
    await loadAccounts()
  } catch (e) {
    importError.value = e.response?.data?.detail || t('login.import_failed')
  } finally {
    importLoading.value = false
  }
}

async function remove(id) {
  if (!confirm(t('common.confirm_delete'))) return
  await deleteAccount(id)
  await loadAccounts()
}

onMounted(loadAccounts)
</script>

<style scoped>
.cookie-import-card {
  max-width: 720px;
}

.form-hint {
  margin-top: 6px;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.5;
}

textarea {
  min-height: 168px;
  resize: vertical;
  font-family: inherit;
}

.empty-state-inline {
  color: var(--text-tertiary);
  font-size: 14px;
  padding: 8px 0;
}

.account-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  gap: 12px;
}
.account-row:last-child { border-bottom: none; }

.account-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.account-username {
  color: var(--text-primary);
  font-weight: 600;
}

.account-email {
  color: var(--text-secondary);
  font-size: 13px;
}

.account-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.account-meta {
  font-size: 12px;
  color: var(--text-tertiary);
}

@media (max-width: 768px) {
  .account-row {
    flex-direction: column;
    align-items: flex-start;
  }
  .account-actions {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
