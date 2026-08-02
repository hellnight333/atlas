import { create } from 'zustand'

import type {
  ApiError,
  ApiStatus,
  AuditRecord,
  IdentityProviderStatus,
  OrgIdentity,
  OrgMembership,
  OrgPermission,
  OrgPolicySet,
  OrgRole,
  OrgTeam,
  Organization,
  OrganizationDetail,
  PermissionResolution,
  PolicyDomain,
  TeamKind,
} from '../api/types'
import { organizationService } from '../services/OrganizationService'
import { toApiError } from '../services/types'

type OrganizationStore = {
  organizations: Organization[]
  activeOrganization: OrganizationDetail | null
  members: OrgMembership[]
  roles: OrgRole[]
  teams: OrgTeam[]
  policySets: OrgPolicySet[]
  auditRecords: AuditRecord[]
  identities: OrgIdentity[]
  identityProviders: IdentityProviderStatus[]
  allPermissions: OrgPermission[]
  permissionResolution: PermissionResolution | null
  actorId: string
  status: ApiStatus
  error: ApiError | null
  loadOrganizations: () => Promise<void>
  switchOrganization: (organizationId: string | null) => Promise<void>
  createOrganization: (name: string, description?: string) => Promise<void>
  addMember: (identityId: string, roleIds: string[]) => Promise<void>
  removeMember: (membershipId: string) => Promise<void>
  createTeam: (name: string, kind: TeamKind) => Promise<void>
  createRole: (name: string, permissions: OrgPermission[]) => Promise<void>
  updateRole: (roleId: string, permissions: OrgPermission[]) => Promise<void>
  upsertPolicy: (domain: PolicyDomain, settings: Record<string, unknown>, lockedKeys: string[]) => Promise<void>
  resolvePermissions: (identityId: string) => Promise<void>
  loadAudit: () => Promise<void>
  setActorId: (actorId: string) => void
}

export const useOrganizationStore = create<OrganizationStore>((set, get) => ({
  organizations: [],
  activeOrganization: null,
  members: [],
  roles: [],
  teams: [],
  policySets: [],
  auditRecords: [],
  identities: [],
  identityProviders: [],
  allPermissions: [],
  permissionResolution: null,
  actorId: 'operator',
  status: 'idle',
  error: null,
  loadOrganizations: async () => {
    set({ status: 'loading', error: null })
    try {
      const [organizations, permissions, identities, identityProviders] = await Promise.all([
        organizationService.list(),
        organizationService.permissions(),
        organizationService.identities(),
        organizationService.identityProviders(),
      ])
      set({
        organizations,
        allPermissions: permissions.map((p) => p.permission),
        identities,
        identityProviders,
        status: organizations.length === 0 ? 'empty' : 'success',
        error: null,
      })
      const current = get().activeOrganization
      const next = organizations.find((o) => o.id === current?.id) ?? organizations[0]
      await get().switchOrganization(next?.id ?? null)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  switchOrganization: async (organizationId) => {
    if (!organizationId) {
      set({
        activeOrganization: null,
        members: [],
        roles: [],
        teams: [],
        policySets: [],
        auditRecords: [],
      })
      return
    }
    try {
      const detail = await organizationService.get(organizationId)
      set({
        activeOrganization: detail ?? null,
        members: detail?.members ?? [],
        roles: detail?.roles ?? [],
        teams: detail?.teams ?? [],
        policySets: detail?.policy_sets ?? [],
      })
      await get().loadAudit()
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  createOrganization: async (name, description) => {
    await mutate(set, get, async () => {
      await organizationService.create({ name, description, actorId: get().actorId })
    })
  },
  addMember: async (identityId, roleIds) => {
    const organizationId = get().activeOrganization?.id
    if (!organizationId) return
    await mutate(set, get, async () => {
      await organizationService.addMember(organizationId, {
        identityId,
        roleIds,
        actorId: get().actorId,
      })
    })
  },
  removeMember: async (membershipId) => {
    const organizationId = get().activeOrganization?.id
    if (!organizationId) return
    await mutate(set, get, async () => {
      await organizationService.removeMember(organizationId, membershipId)
    })
  },
  createTeam: async (name, kind) => {
    const organizationId = get().activeOrganization?.id
    if (!organizationId) return
    await mutate(set, get, async () => {
      await organizationService.createTeam({ organizationId, name, kind })
    })
  },
  createRole: async (name, permissions) => {
    const organizationId = get().activeOrganization?.id
    if (!organizationId) return
    await mutate(set, get, async () => {
      await organizationService.createRole({ name, permissions, organizationId })
    })
  },
  updateRole: async (roleId, permissions) => {
    await mutate(set, get, async () => {
      await organizationService.updateRole(roleId, permissions)
    })
  },
  upsertPolicy: async (domain, settings, lockedKeys) => {
    const organizationId = get().activeOrganization?.id
    if (!organizationId) return
    await mutate(set, get, async () => {
      await organizationService.upsertPolicySet({
        organizationId,
        domain,
        settings,
        lockedKeys,
        actorId: get().actorId,
      })
    })
  },
  resolvePermissions: async (identityId) => {
    const organizationId = get().activeOrganization?.id
    if (!organizationId) return
    try {
      const resolution = await organizationService.resolvePermissions(organizationId, identityId)
      set({ permissionResolution: resolution })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  loadAudit: async () => {
    const organizationId = get().activeOrganization?.id
    try {
      const auditRecords = await organizationService.audit({ organizationId, limit: 100 })
      set({ auditRecords })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  setActorId: (actorId) => set({ actorId }),
}))

type SetState = (partial: Partial<ReturnType<typeof useOrganizationStore.getState>>) => void
type GetState = () => ReturnType<typeof useOrganizationStore.getState>

async function mutate(set: SetState, get: GetState, operation: () => Promise<void>): Promise<void> {
  set({ status: 'refreshing', error: null })
  try {
    await operation()
    set({ status: 'success', error: null })
    await get().loadOrganizations()
  } catch (error) {
    set({ status: 'error', error: toApiError(error) })
  }
}
