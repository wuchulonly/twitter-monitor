import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN.js'
import en from './en.js'

const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('lang') : null

export default createI18n({
  legacy: false,
  locale: saved || 'zh-CN',
  fallbackLocale: 'en',
  messages: {
    'zh-CN': zhCN,
    en,
  },
})
