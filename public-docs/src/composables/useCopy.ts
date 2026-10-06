import { ref } from 'vue'
import { trackCodeCopy } from '@/lib/analytics'

// Copy text to the clipboard and expose a transient `copied` flag for
// "Copied!" button feedback. Overlapping copies reset the timer rather than
// stacking, so the flag always clears `resetDelay` ms after the last copy.
export function useCopy(resetDelay = 2000) {
  const copied = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    trackCodeCopy()
    copied.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      copied.value = false
      timer = null
    }, resetDelay)
  }

  return { copied, copy }
}
