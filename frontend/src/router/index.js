import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/tweets', name: 'Tweets', component: () => import('../views/Tweets.vue') },
  { path: '/monitors', name: 'Monitors', component: () => import('../views/Monitors.vue') },
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
