import { useEffect, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useOrganizationStore } from '../../../stores'
import type { OrgPermission, PolicyDomain, TeamKind } from '../../../api/types'

const TEAM_KINDS: TeamKind[] = [
  'engineering',
  'research',
  'creative',
  'operations',
  'management',
  'custom',
]

const POLICY_DOMAINS: PolicyDomain[] = [
  'approval',
  'automation',
  'workers',
  'plugins',
  'providers',
  'storage',
  'retention',
  'sharing',
  'publishing',
  'security',
]

export function OrganizationStudioScreen() {
  const organizations = useOrganizationStore((state) => state.organizations)
  const active = useOrganizationStore((state) => state.activeOrganization)
  const members = useOrganizationStore((state) => state.members)
  const roles = useOrganizationStore((state) => state.roles)
  const teams = useOrganizationStore((state) => state.teams)
  const policySets = useOrganizationStore((state) => state.policySets)
  const auditRecords = useOrganizationStore((state) => state.auditRecords)
  const identities = useOrganizationStore((state) => state.identities)
  const identityProviders = useOrganizationStore((state) => state.identityProviders)
  const allPermissions = useOrganizationStore((state) => state.allPermissions)
  const resolution = useOrganizationStore((state) => state.permissionResolution)
  const status = useOrganizationStore((state) => state.status)
  const error = useOrganizationStore((state) => state.error)

  const loadOrganizations = useOrganizationStore((state) => state.loadOrganizations)
  const switchOrganization = useOrganizationStore((state) => state.switchOrganization)
  const createOrganization = useOrganizationStore((state) => state.createOrganization)
  const addMember = useOrganizationStore((state) => state.addMember)
  const removeMember = useOrganizationStore((state) => state.removeMember)
  const createTeam = useOrganizationStore((state) => state.createTeam)
  const createRole = useOrganizationStore((state) => state.createRole)
  const resolvePermissions = useOrganizationStore((state) => state.resolvePermissions)
  const upsertPolicy = useOrganizationStore((state) => state.upsertPolicy)

  const [orgName, setOrgName] = useState('')
  const [teamName, setTeamName] = useState('')
  const [teamKind, setTeamKind] = useState<TeamKind>('engineering')
  const [roleName, setRoleName] = useState('')
  const [rolePermissions, setRolePermissions] = useState<OrgPermission[]>([])
  const [memberIdentity, setMemberIdentity] = useState('')
  const [memberRole, setMemberRole] = useState('')
  const [policyDomain, setPolicyDomain] = useState<PolicyDomain>('security')
  const [policyJson, setPolicyJson] = useState('{"require_mfa": true}')
  const [lockedKeys, setLockedKeys] = useState('')

  useEffect(() => {
    void loadOrganizations()
  }, [loadOrganizations])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[300px_minmax(0,1fr)_360px]">
      <Panel title="Organizations" subtitle={`${organizations.length} tenant(s)`}>
        <div className="space-y-3">
          {error ? (
            <p className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error.message}
            </p>
          ) : null}

          {organizations.length === 0 ? (
            <p className="rounded border border-dashed border-slate-700 px-3 py-6 text-center text-sm text-slate-500">
              {status === 'loading' ? 'Loading organizations…' : 'No organizations yet.'}
            </p>
          ) : null}

          <div className="space-y-2">
            {organizations.map((organization) => (
              <button
                key={organization.id}
                type="button"
                onClick={() => void switchOrganization(organization.id)}
                className={`block w-full rounded border px-3 py-2 text-left ${
                  active?.id === organization.id
                    ? 'border-cyan-500/50 bg-cyan-500/10'
                    : 'border-slate-800 bg-slate-900 hover:bg-slate-800'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-100">{organization.name}</span>
                  <span className="text-xs uppercase tracking-widest text-slate-500">
                    {organization.license.tier}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {organization.slug} · {organization.active ? 'active' : 'archived'}
                </p>
              </button>
            ))}
          </div>

          <div className="space-y-2 border-t border-slate-800 pt-3">
            <input
              className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100"
              placeholder="New organization name"
              value={orgName}
              onChange={(event) => setOrgName(event.target.value)}
            />
            <Button
              variant="accent"
              className="w-full"
              disabled={!orgName.trim()}
              onClick={() => {
                void createOrganization(orgName.trim())
                setOrgName('')
              }}
            >
              Create Organization
            </Button>
          </div>
        </div>
      </Panel>

      <div className="space-y-4">
        <Panel
          title={active?.name ?? 'Organization'}
          subtitle={
            active
              ? `${active.slug} · tenant ${active.tenant_id} · ${active.license.tier} · ${active.license.seats} seats`
              : 'Select an organization'
          }
        >
          {active ? (
            <div className="grid gap-2 md:grid-cols-4">
              <Stat label="Members" value={String(members.length)} />
              <Stat label="Teams" value={String(teams.length)} />
              <Stat label="Roles" value={String(roles.length)} />
              <Stat label="Policies" value={String(policySets.length)} />
            </div>
          ) : null}
        </Panel>

        <Panel title="Members" subtitle="Identity, roles and permission source">
          <div className="space-y-3">
            <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
              <select
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={memberIdentity}
                onChange={(event) => setMemberIdentity(event.target.value)}
              >
                <option value="">Select identity…</option>
                {identities.map((identity) => (
                  <option key={identity.id} value={identity.id}>
                    {identity.display_name}
                  </option>
                ))}
              </select>
              <select
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={memberRole}
                onChange={(event) => setMemberRole(event.target.value)}
              >
                <option value="">Select role…</option>
                {roles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
              <Button
                disabled={!memberIdentity || !memberRole}
                onClick={() => void addMember(memberIdentity, [memberRole])}
              >
                Add Member
              </Button>
            </div>

            {members.length === 0 ? (
              <p className="text-sm text-slate-500">No members yet.</p>
            ) : (
              <ul className="space-y-2">
                {members.map((membership) => {
                  const identity = identities.find((i) => i.id === membership.identity_id)
                  return (
                    <li
                      key={membership.id}
                      className="flex items-center justify-between gap-2 rounded bg-slate-900 px-3 py-2 text-sm"
                    >
                      <div>
                        <div className="text-slate-100">
                          {identity?.display_name ?? membership.identity_id}
                        </div>
                        <p className="text-xs text-slate-500">
                          {membership.role_ids
                            .map((id) => roles.find((r) => r.id === id)?.name ?? id)
                            .join(', ') || 'no roles'}
                          {membership.expires_at
                            ? ` · expires ${new Date(membership.expires_at).toLocaleDateString()}`
                            : ''}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="ghost"
                          onClick={() => void resolvePermissions(membership.identity_id)}
                        >
                          Permissions
                        </Button>
                        <Button variant="ghost" onClick={() => void removeMember(membership.id)}>
                          Remove
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </Panel>

        <Panel title="Teams" subtitle="Teams own projects, studios, workers and automation">
          <div className="space-y-3">
            <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
              <input
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                placeholder="Team name"
                value={teamName}
                onChange={(event) => setTeamName(event.target.value)}
              />
              <select
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={teamKind}
                onChange={(event) => setTeamKind(event.target.value as TeamKind)}
              >
                {TEAM_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
              <Button
                disabled={!teamName.trim() || !active}
                onClick={() => {
                  void createTeam(teamName.trim(), teamKind)
                  setTeamName('')
                }}
              >
                Create Team
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {teams.map((team) => (
                <span key={team.id} className="rounded bg-slate-900 px-2 py-1 text-xs text-slate-300">
                  {team.name} · {team.kind}
                </span>
              ))}
            </div>
          </div>
        </Panel>

        <Panel title="Roles" subtitle="Roles are permission collections — never hardcoded checks">
          <div className="space-y-3">
            <div className="grid gap-2 md:grid-cols-[1fr_auto]">
              <input
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                placeholder="Custom role name"
                value={roleName}
                onChange={(event) => setRoleName(event.target.value)}
              />
              <Button
                disabled={!roleName.trim() || rolePermissions.length === 0}
                onClick={() => {
                  void createRole(roleName.trim(), rolePermissions)
                  setRoleName('')
                  setRolePermissions([])
                }}
              >
                Create Role
              </Button>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {allPermissions.map((permission) => {
                const selected = rolePermissions.includes(permission)
                return (
                  <button
                    key={permission}
                    type="button"
                    onClick={() =>
                      setRolePermissions((current) =>
                        selected
                          ? current.filter((p) => p !== permission)
                          : [...current, permission],
                      )
                    }
                    className={`rounded px-2 py-1 text-[11px] ${
                      selected
                        ? 'bg-cyan-500/20 text-cyan-200'
                        : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                    }`}
                  >
                    {permission}
                  </button>
                )
              })}
            </div>

            <ul className="space-y-1.5">
              {roles.map((role) => (
                <li key={role.id} className="rounded bg-slate-900 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-100">{role.name}</span>
                    <span className="text-xs uppercase tracking-widest text-slate-500">
                      {role.builtin ? 'built-in' : 'custom'}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {role.permissions.length} permission(s)
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </Panel>

        <Panel title="Policies" subtitle="Organization → Workspace → Project → Object">
          <div className="space-y-3">
            <div className="grid gap-2 md:grid-cols-[1fr_1fr]">
              <select
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={policyDomain}
                onChange={(event) => setPolicyDomain(event.target.value as PolicyDomain)}
              >
                {POLICY_DOMAINS.map((domain) => (
                  <option key={domain} value={domain}>
                    {domain}
                  </option>
                ))}
              </select>
              <input
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                placeholder="Locked keys (comma separated)"
                value={lockedKeys}
                onChange={(event) => setLockedKeys(event.target.value)}
              />
            </div>
            <textarea
              className="min-h-20 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100"
              value={policyJson}
              onChange={(event) => setPolicyJson(event.target.value)}
            />
            <Button
              disabled={!active}
              onClick={() => {
                let settings: Record<string, unknown> = {}
                try {
                  settings = JSON.parse(policyJson) as Record<string, unknown>
                } catch {
                  return
                }
                void upsertPolicy(
                  policyDomain,
                  settings,
                  lockedKeys
                    .split(',')
                    .map((k) => k.trim())
                    .filter(Boolean),
                )
              }}
            >
              Save Policy
            </Button>

            <ul className="space-y-1.5">
              {policySets.map((policy) => (
                <li key={policy.id} className="rounded bg-slate-900 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-100">{policy.domain}</span>
                    <span className="text-xs uppercase tracking-widest text-slate-500">
                      {policy.scope}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-slate-500">
                    {JSON.stringify(policy.settings)}
                  </p>
                  {policy.locked_keys.length > 0 ? (
                    <p className="text-[11px] text-amber-300">
                      locked: {policy.locked_keys.join(', ')}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        </Panel>
      </div>

      <div className="space-y-4">
        <Panel title="Permission Resolution" subtitle="Why an identity holds what it holds">
          {resolution ? (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">
                {resolution.permissions.length} permission(s) via{' '}
                {resolution.role_ids.length} role(s)
              </p>
              <ul className="space-y-1">
                {resolution.grants.map((grant) => (
                  <li key={grant.permission} className="rounded bg-slate-900 px-3 py-1.5 text-xs">
                    <span className="text-slate-100">{grant.permission}</span>
                    <span className="ml-2 text-slate-500">{grant.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Select a member to resolve permissions.</p>
          )}
        </Panel>

        <Panel title="Branding &amp; License" subtitle="Entitlement only — no billing">
          {active ? (
            <div className="space-y-1.5">
              <Row label="Display Name" value={active.branding.display_name ?? active.name} />
              <Row label="Accent" value={active.branding.accent_color ?? 'default'} />
              <Row label="Theme" value={active.branding.theme ?? 'default'} />
              <Row label="Tier" value={active.license.tier} />
              <Row label="Seats" value={String(active.license.seats)} />
              <Row label="Max Workers" value={String(active.license.max_workers)} />
              <Row
                label="Shared Pool"
                value={active.allow_shared_pool ? 'allowed' : 'forbidden'}
              />
            </div>
          ) : (
            <p className="text-sm text-slate-500">No organization selected.</p>
          )}
        </Panel>

        <Panel title="Identity Providers" subtitle="Interfaces only in this build">
          <ul className="space-y-1">
            {identityProviders.map((provider) => (
              <li
                key={provider.kind}
                className="flex items-center justify-between rounded bg-slate-900 px-3 py-1.5 text-xs"
              >
                <span className="text-slate-200">{provider.kind}</span>
                <span className={provider.implemented ? 'text-emerald-300' : 'text-slate-500'}>
                  {provider.implemented ? 'available' : 'interface only'}
                </span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Audit Trail" subtitle="Append-only">
          {auditRecords.length === 0 ? (
            <p className="text-sm text-slate-500">No audit records.</p>
          ) : (
            <ul className="space-y-2">
              {auditRecords.slice(0, 12).map((record) => (
                <li key={record.id} className="rounded bg-slate-900 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs uppercase tracking-widest text-slate-500">
                      {record.action}
                    </span>
                    <span className="text-xs text-slate-500">{record.actor_display}</span>
                  </div>
                  <p className="mt-1 text-slate-200">{record.summary}</p>
                  <p className="text-xs text-slate-500">
                    {new Date(record.created_at).toLocaleString()}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-900 px-3 py-2">
      <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-medium text-slate-100">{value}</div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 rounded bg-slate-900 px-3 py-1.5">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs text-slate-200">{value}</span>
    </div>
  )
}
