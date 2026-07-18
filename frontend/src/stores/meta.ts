import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'

/**
 * App-level instance metadata from `/api/meta` (version, storage, and whether
 * the instance is read-only). Loaded once after auth; the read-only flag drives
 * the demo banner and lets the UI hide write actions. The server enforces
 * read-only regardless — this is presentation only.
 */
export const useMetaStore = defineStore('meta', () => {
  const readOnly = ref(false)
  const storage = ref<'local' | 'server'>('server')
  const loaded = ref(false)

  async function ensureLoaded(): Promise<void> {
    if (loaded.value) return
    const res = await api.GET('/api/meta')
    if (res.data) {
      readOnly.value = res.data.read_only
      storage.value = res.data.storage === 'local' ? 'local' : 'server'
      loaded.value = true
    }
  }

  return { readOnly, storage, loaded, ensureLoaded }
})
