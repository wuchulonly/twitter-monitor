<template>
  <div>
    <h1 class="page-title page-header">{{ $t('tweets.title') }}</h1>

    <div class="search-bar">
      <div class="search-input-wrap">
        <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"/>
          <line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input
          v-model="filterAuthor"
          :placeholder="$t('tweets.filter_placeholder')"
          class="search-input"
          @keyup.enter="searchTweets"
        />
      </div>
      <button
        class="btn btn-sm"
        :class="mediaType === 'photo' ? 'btn-primary' : 'btn-ghost'"
        type="button"
        @click="toggleMediaType('photo')"
      >
        {{ $t('tweets.images_only') }}
      </button>
      <button
        class="btn btn-sm"
        :class="mediaType === 'video' ? 'btn-primary' : 'btn-ghost'"
        type="button"
        @click="toggleMediaType('video')"
      >
        {{ $t('tweets.videos_only') }}
      </button>
      <button class="btn btn-primary btn-sm" type="button" @click="searchTweets">{{ $t('common.search') }}</button>
      <button class="btn btn-ghost btn-sm" type="button" @click="clearFilters">{{ $t('common.clear') }}</button>
    </div>

    <div v-if="authorOptions.length" class="author-filters">
      <div class="author-filters-label">{{ $t('tweets.authors_label') }}</div>
      <div class="author-filter-list">
        <button
          class="btn btn-sm"
          :class="selectedAuthors.length ? 'btn-ghost' : 'btn-primary'"
          type="button"
          @click="applyAuthorFilter('')"
        >
          {{ $t('tweets.all_authors') }}
        </button>
        <button
          v-for="author in authorOptions"
          :key="author.author_username"
          class="btn btn-sm author-filter-btn"
          :class="isAuthorActive(author.author_username) ? 'btn-primary' : 'btn-ghost'"
          type="button"
          @click="applyAuthorFilter(author.author_username)"
        >
          <span>@{{ author.author_username }}</span>
          <span class="author-filter-count">{{ author.tweet_count }}</span>
        </button>
      </div>
    </div>

    <div v-if="!tweets.length" class="card empty-state">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"/>
        <line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      <p>{{ $t('tweets.no_tweets') }}</p>
    </div>

    <div v-for="group in groupedTweets" :key="group.author" class="tweet-group">
      <div class="tweet-group-header">
        <div class="tweet-group-user">@{{ group.author }}</div>
        <div class="tweet-group-count">{{ $t('tweets.group_count', { count: group.tweets.length }) }}</div>
      </div>
      <TweetCard v-for="t in group.tweets" :key="t.id" :tweet="t" />
    </div>

    <div v-if="totalPages > 1" class="pagination-wrap">
      <div class="pagination-summary">
        {{ $t('tweets.page_summary', { page, totalPages, total: totalCount }) }}
      </div>
      <div class="pagination-controls">
        <button class="btn btn-sm btn-ghost" :disabled="loading || page <= 1" @click="goToPage(page - 1)">
          {{ $t('tweets.prev_page') }}
        </button>
        <button
          v-for="pageNumber in visiblePages"
          :key="pageNumber"
          class="btn btn-sm"
          :class="pageNumber === page ? 'btn-primary' : 'btn-ghost'"
          :disabled="loading"
          @click="goToPage(pageNumber)"
        >
          {{ pageNumber }}
        </button>
        <button class="btn btn-sm btn-ghost" :disabled="loading || page >= totalPages" @click="goToPage(page + 1)">
          {{ $t('tweets.next_page') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { getTweetAuthors, getTweetMeta, getTweets } from '../api/index.js'
import TweetCard from '../components/TweetCard.vue'

const tweets = ref([])
const authorOptions = ref([])
const filterAuthor = ref('')
const mediaType = ref('')
const page = ref(1)
const pageSize = 20
const totalCount = ref(0)
const totalPages = ref(1)
const loading = ref(false)

const selectedAuthors = computed(() => parseAuthors(filterAuthor.value))
const selectedAuthorKeys = computed(() => new Set(selectedAuthors.value.map((author) => author.toLowerCase())))

const groupedTweets = computed(() => {
  const groups = new Map()
  for (const tweet of tweets.value) {
    const author = tweet.author_username || 'unknown'
    if (!groups.has(author)) {
      groups.set(author, { author, tweets: [] })
    }
    groups.get(author).tweets.push(tweet)
  }
  return Array.from(groups.values())
})

const visiblePages = computed(() => {
  const pages = []
  const start = Math.max(1, page.value - 2)
  const end = Math.min(totalPages.value, start + 4)
  const adjustedStart = Math.max(1, end - 4)

  for (let current = adjustedStart; current <= end; current += 1) {
    pages.push(current)
  }
  return pages
})

function normalizeAuthor(value) {
  return value.trim().replace(/^@+/, '').trim()
}

function canonicalizeAuthor(value) {
  const normalized = normalizeAuthor(value)
  if (!normalized) return ''
  const match = authorOptions.value.find(
    ({ author_username }) => normalizeAuthor(author_username).toLowerCase() === normalized.toLowerCase(),
  )
  return match ? normalizeAuthor(match.author_username) : normalized
}

function parseAuthors(value) {
  const authors = []
  const seen = new Set()

  for (const item of value.split(/[,\n，]+/)) {
    const author = canonicalizeAuthor(item)
    if (!author) continue
    const authorKey = author.toLowerCase()
    if (seen.has(authorKey)) continue
    seen.add(authorKey)
    authors.push(author)
  }

  return authors
}

function formatAuthors(authors) {
  return authors.map((author) => `@${canonicalizeAuthor(author)}`).join(', ')
}

function isAuthorActive(author) {
  return selectedAuthorKeys.value.has(normalizeAuthor(author).toLowerCase())
}

async function loadAuthors() {
  const { data } = await getTweetAuthors()
  authorOptions.value = data
}

async function load() {
  loading.value = true
  const params = { page: page.value, size: pageSize }
  if (selectedAuthors.value.length) params.author = selectedAuthors.value
  if (mediaType.value) params.media_type = mediaType.value
  try {
    const [{ data }, { data: meta }] = await Promise.all([
      getTweets(params),
      getTweetMeta(params),
    ])
    tweets.value = data
    totalCount.value = meta.total
    totalPages.value = meta.total_pages
  } finally {
    loading.value = false
  }
}

async function searchTweets() {
  filterAuthor.value = formatAuthors(selectedAuthors.value)
  page.value = 1
  await load()
}

async function toggleMediaType(nextType) {
  mediaType.value = mediaType.value === nextType ? '' : nextType
  await searchTweets()
}

async function applyAuthorFilter(author) {
  if (!author) {
    filterAuthor.value = ''
    await searchTweets()
    return
  }

  const normalizedAuthor = canonicalizeAuthor(author)
  const nextAuthors = selectedAuthors.value.filter((item) => item.toLowerCase() !== normalizedAuthor.toLowerCase())

  if (nextAuthors.length === selectedAuthors.value.length) {
    nextAuthors.push(normalizedAuthor)
  }

  filterAuthor.value = formatAuthors(nextAuthors)
  await searchTweets()
}

async function clearFilters() {
  filterAuthor.value = ''
  mediaType.value = ''
  await searchTweets()
}

async function goToPage(nextPage) {
  if (loading.value || nextPage < 1 || nextPage > totalPages.value || nextPage === page.value) return
  page.value = nextPage
  await load()
}

onMounted(async () => {
  await Promise.all([load(), loadAuthors()])
})
</script>

<style scoped>
.search-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.search-input-wrap {
  position: relative;
  flex: 1;
  max-width: 320px;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
  pointer-events: none;
}

.search-input {
  padding-left: 36px;
}

.author-filters {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 20px;
}

.author-filters-label {
  flex-shrink: 0;
  padding-top: 6px;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.author-filter-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.author-filter-btn {
  padding-right: 10px;
}

.author-filter-count {
  min-width: 20px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: inherit;
  font-size: 11px;
  line-height: 1.2;
}

.btn-primary .author-filter-count {
  background: rgba(10, 10, 15, 0.14);
}

.btn-ghost .author-filter-count {
  background: var(--accent-dim);
}

.tweet-group {
  margin-bottom: 24px;
}

.tweet-group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.tweet-group-user {
  color: var(--accent);
  font-size: 18px;
  font-weight: 700;
}

.tweet-group-count {
  color: var(--text-tertiary);
  font-size: 12px;
  font-weight: 500;
}

.pagination-wrap {
  margin-top: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pagination-summary {
  color: var(--text-tertiary);
  font-size: 12px;
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 768px) {
  .search-input-wrap {
    max-width: none;
  }

  .author-filters {
    flex-direction: column;
    gap: 10px;
  }

  .author-filters-label {
    padding-top: 0;
  }

  .tweet-group-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .pagination-wrap {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
