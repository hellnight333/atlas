import type { NotificationItem as NotificationType } from '../types/domain'
import { StatusIndicator } from './StatusIndicator'

export function Notification({ notification }: { notification: NotificationType }) {
  return (
    <div className="rounded border border-slate-700 bg-slate-950 p-3 shadow-lg">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-100">{notification.title}</p>
        <StatusIndicator severity={notification.severity} label={notification.severity} />
      </div>
      <p className="mt-1 text-xs text-slate-400">{notification.detail}</p>
    </div>
  )
}
