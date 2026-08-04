import { useEffect } from 'react'

import { logStartup } from '../api/shell'

/**
 * Records what actually ended up on screen.
 *
 * "The tree mounted and nothing threw" and "the user can see something" are
 * different claims, and only the first one was ever being checked. A blank
 * window with a healthy log is the exact shape of the bug that cost a day, and
 * no amount of lifecycle logging distinguishes it from a working app.
 *
 * So this measures the rendered document once, a frame after mount: how many
 * elements exist, how much text is visible, and how tall the content is. A
 * mounted-but-empty tree reports zero, and zero is a symptom rather than a
 * silence.
 *
 * Measured after two frames because layout has not settled on the first — a
 * height read too early is zero for reasons that are not a bug, which would
 * make the probe cry wolf and then be ignored.
 */
export function RenderProbe({ label }: { label: string }) {
  useEffect(() => {
    let cancelled = false

    const measure = () => {
      if (cancelled) return
      const root = document.getElementById('root')
      if (!root) {
        logStartup(`render probe [${label}]: no #root element`)
        return
      }

      const elements = root.querySelectorAll('*').length
      const text = (root.textContent ?? '').trim().length
      const rect = root.getBoundingClientRect()
      const painted = elements > 0 && rect.height > 0

      logStartup(
        `render probe [${label}]: ${elements} elements, ${text} chars, ` +
          `${Math.round(rect.width)}x${Math.round(rect.height)} — ` +
          (painted ? 'visible content' : 'NOTHING VISIBLE'),
      )
    }

    const frame = requestAnimationFrame(() => requestAnimationFrame(measure))
    return () => {
      cancelled = true
      cancelAnimationFrame(frame)
    }
  }, [label])

  return null
}
