import { create } from 'zustand'

import { activityService } from '../services/ActivityService'
import { toApiError } from '../services/types'
import type { ApiError, ApiStatus } from '../api/types'
import type { NotificationItem } from '../types/domain'

type NotificationStore = {
  notifications: NotificationItem[]
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
  loadNotifications: () => Promise<void>
  refreshNotifications: () => Promise<void>
}

export const useNotificationStore = create<NotificationStore>((set) => ({
  notifications: [],
  status: 'idle',
  error: null,
  lastLoadedAt: null,
  loadNotifications: async () => {
    set((state) => ({ status: state.notifications.length > 0 ? 'refreshing' : 'loading', error: null }))
    try {
      const notifications = await activityService.listNotifications()
      set({
        notifications,
        status: notifications.length === 0 ? 'empty' : 'success',
        error: null,
        lastLoadedAt: Date.now(),
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshNotifications: async () => {
    await useNotificationStore.getState().loadNotifications()
  },
}))
