import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

const serializeParams = (params = {}) => {
  const searchParams = new URLSearchParams()

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === '') continue
        searchParams.append(key, item)
      }
      continue
    }
    searchParams.append(key, value)
  }

  return searchParams.toString()
}

// Auth
export const importCookies = (data) => api.post('/auth/import-cookies', data)
export const getAccounts = () => api.get('/auth/accounts')
export const deleteAccount = (id) => api.delete(`/auth/accounts/${id}`)

// Monitors
export const getMonitors = () => api.get('/monitors')
export const createMonitor = (data) => api.post('/monitors', data)
export const createMonitorsBulk = (data) => api.post('/monitors/bulk', data)
export const deleteMonitor = (id) => api.delete(`/monitors/${id}`)
export const backfillMonitor = (id, data) => api.post(`/monitors/${id}/backfill`, data)
export const updateMonitor = (id, params) => api.patch(`/monitors/${id}`, null, { params })

// Tweets
export const getTweets = (params) => api.get('/tweets', { params, paramsSerializer: serializeParams })
export const getTweetAuthors = () => api.get('/tweets/authors')
export const getTweetMeta = (params) => api.get('/tweets/meta', { params, paramsSerializer: serializeParams })
export const getTweet = (id) => api.get(`/tweets/${id}`)

// Settings
export const getChannels = () => api.get('/settings/channels')
export const createChannel = (data) => api.post('/settings/channels', data)
export const updateChannel = (id, data) => api.put(`/settings/channels/${id}`, data)
export const deleteChannel = (id) => api.delete(`/settings/channels/${id}`)
export const testChannel = (id) => api.post(`/settings/channels/${id}/test`)

// System
export const triggerCheck = () => api.post('/check-now')
