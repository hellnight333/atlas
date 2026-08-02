import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  useCommandPaletteStore,
  useMissionControlStore,
  useUIStore,
} from '../stores'

export function useGlobalShortcuts() {
  const navigate = useNavigate()
  const setCommandOpen = useCommandPaletteStore((state) => state.setOpen)
  const setMissionOpen = useMissionControlStore((state) => state.setOpen)
  const setActivityCenterOpen = useUIStore((state) => state.setActivityCenterOpen)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const metaOrCtrl = event.metaKey || event.ctrlKey

      if (metaOrCtrl && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(true)
      }

      if (metaOrCtrl && event.key.toLowerCase() === 'm') {
        event.preventDefault()
        setMissionOpen(true)
        navigate('/mission-control')
      }

      if (event.key === 'Escape') {
        setCommandOpen(false)
        setMissionOpen(false)
        setActivityCenterOpen(false)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [navigate, setActivityCenterOpen, setCommandOpen, setMissionOpen])
}
