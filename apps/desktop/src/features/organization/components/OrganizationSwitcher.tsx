import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import { useOrganizationStore } from '../../../stores'

export function OrganizationSwitcher() {
  const navigate = useNavigate()
  const organizations = useOrganizationStore((state) => state.organizations)
  const active = useOrganizationStore((state) => state.activeOrganization)
  const loadOrganizations = useOrganizationStore((state) => state.loadOrganizations)
  const switchOrganization = useOrganizationStore((state) => state.switchOrganization)

  useEffect(() => {
    void loadOrganizations()
  }, [loadOrganizations])

  if (organizations.length === 0) {
    return (
      <button
        type="button"
        onClick={() => navigate('/organizations')}
        className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
      >
        No organization
      </button>
    )
  }

  const accent = active?.branding.accent_color ?? undefined

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="Organization"
        className="rounded bg-cyan-500/10 px-2 py-1 text-xs text-cyan-300"
        style={accent ? { color: accent } : undefined}
        value={active?.id ?? ''}
        onChange={(event) => void switchOrganization(event.target.value)}
      >
        {organizations.map((organization) => (
          <option key={organization.id} value={organization.id}>
            {organization.branding.display_name ?? organization.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => navigate('/organizations')}
        className="text-xs text-slate-400 hover:text-slate-200"
      >
        Manage
      </button>
    </div>
  )
}
