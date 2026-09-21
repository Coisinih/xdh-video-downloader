import { ViteSSG } from 'vite-ssg/single-page'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'
import './workspace.css'
import './result-reference.css'
import './seo-content.css'
import './membership.css'
import './responsive-overrides.css'
import './membership-compact.css'

export const createApp = ViteSSG(App, ({ app }) => {
  app.use(createPinia())
})
