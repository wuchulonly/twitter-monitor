<template>
  <div class="tweet-card">
    <div class="tweet-header">
      <a :href="`https://x.com/${tweet.author_username}`" target="_blank" class="tweet-author">
        @{{ tweet.author_username }}
      </a>
      <span class="tweet-time mono">{{ formatTime(tweet.tweet_created_at) }}</span>
    </div>
    <div class="tweet-content">{{ tweet.content }}</div>
    <div v-if="mediaItems.length" class="tweet-media">
      <template v-for="(item, idx) in mediaItems" :key="idx">
        <img
          v-if="item.type === 'photo'"
          :src="item.url"
          alt="media"
          class="media-img"
          @click="previewUrl = item.url"
        />
        <video
          v-else-if="item.type === 'video'"
          controls
          preload="none"
          :poster="item.thumbnail"
          class="media-video"
        >
          <source :src="item.url" type="video/mp4" />
        </video>
        <video
          v-else-if="item.type === 'animated_gif'"
          autoplay
          loop
          muted
          playsinline
          preload="none"
          :poster="item.thumbnail"
          class="media-video"
        >
          <source :src="item.url" type="video/mp4" />
        </video>
      </template>
    </div>
    <div class="tweet-footer">
      <a :href="`https://x.com/${tweet.author_username}/status/${tweet.tweet_id}`" target="_blank" class="tweet-link">
        {{ $t('tweets.view_on_x') }}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
          <polyline points="15 3 21 3 21 9"/>
          <line x1="10" y1="14" x2="21" y2="3"/>
        </svg>
      </a>
      <span v-if="tweet.is_notified" class="tag tag-info">{{ $t('common.notified') }}</span>
    </div>

    <div v-if="previewUrl" class="preview-overlay" @click="previewUrl = null">
      <img :src="previewUrl" class="preview-img" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({ tweet: Object })
const previewUrl = ref(null)

const mediaItems = computed(() => {
  const urls = props.tweet.media_urls
  if (!urls || !urls.length) return []
  return urls
    .map(item => {
      if (typeof item === 'string') {
        return { type: 'photo', url: item }
      }
      return item
    })
    .filter(item => {
      if (!item?.url) return false
      if (item.type === 'photo') {
        return !item.url.startsWith('https://t.co/')
      }
      return true
    })
})

function formatTime(t) {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN')
}
</script>

<style scoped>
.tweet-card {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-left: 2px solid var(--accent);
  border-radius: var(--radius-md);
  padding: 16px 20px;
  margin-bottom: 12px;
  overflow: hidden;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.tweet-card:hover {
  border-color: var(--border-active);
  border-left-color: var(--accent);
  transform: translateY(-1px);
}

.tweet-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.tweet-author {
  color: var(--accent);
  font-weight: 600;
  font-size: 14px;
  text-decoration: none;
  transition: opacity 0.15s;
}
.tweet-author:hover { opacity: 0.8; }

.tweet-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.tweet-content {
  color: var(--text-primary);
  line-height: 1.7;
  margin-bottom: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
}

.tweet-media {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  width: 100%;
  margin-bottom: 12px;
}

.media-img {
  max-width: 280px;
  max-height: 280px;
  display: block;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  object-fit: cover;
  cursor: pointer;
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.media-img:hover {
  transform: scale(1.02);
  opacity: 0.9;
}

.media-video {
  max-width: 400px;
  max-height: 300px;
  display: block;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-primary);
}

.tweet-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tweet-link {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: color 0.15s;
}
.tweet-link:hover { color: var(--accent); }

.preview-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.92);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  cursor: pointer;
  animation: fadeIn 0.15s ease;
}

.preview-img {
  max-width: 90vw;
  max-height: 90vh;
  border-radius: var(--radius-md);
  object-fit: contain;
  animation: scaleIn 0.2s ease;
}

@keyframes scaleIn {
  from { transform: scale(0.92); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

@media (max-width: 768px) {
  .tweet-card {
    padding: 14px 16px;
  }

  .tweet-header,
  .tweet-footer {
    gap: 8px;
    flex-wrap: wrap;
  }

  .media-img,
  .media-video {
    width: 100%;
    max-width: 100%;
    height: auto;
  }
}
</style>
