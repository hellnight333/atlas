import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  AuditAction,
  AuditRecord,
  IdentityProviderStatus,
  MemberAddPayload,
  OrgIdentity,
  OrgMembership,
  OrgPermission,
  OrgPolicySet,
  OrgRole,
  OrgTeam,
  Organization,
  OrganizationCreatePayload,
  OrganizationDetail,
  PermissionResolution,
  PolicyDomain,
  PolicySetPayload,
  ResolvedPolicy,
  TeamKind,
} from '../api/types'

export interface OrganizationService {
  list(identityId?: string): Promise<Organization[]>
  get(id: string): Promise<OrganizationDetail | undefined>
  create(payload: OrganizationCreatePayload): Promise<Organization>
  update(id: string, changes: Partial<Organization>): Promise<Organization>
  members(id: string): Promise<OrgMembership[]>
  addMember(id: string, payload: MemberAddPayload): Promise<OrgMembership>
  removeMember(organizationId: string, membershipId: string): Promise<void>
  resolvePermissions(organizationId: string, identityId: string): Promise<PermissionResolution>
  assignWorker(organizationId: string, workerId: string): Promise<void>
  roles(organizationId?: string): Promise<OrgRole[]>
  createRole(payload: {
    name: string
    permissions: OrgPermission[]
    organizationId?: string
    description?: string
  }): Promise<OrgRole>
  updateRole(roleId: string, permissions: OrgPermission[]): Promise<OrgRole>
  permissions(): Promise<Array<{ permission: OrgPermission; name: string }>>
  teams(organizationId?: string): Promise<OrgTeam[]>
  createTeam(payload: {
    organizationId: string
    name: string
    kind?: TeamKind
    description?: string
  }): Promise<OrgTeam>
  policySets(organizationId?: string, domain?: PolicyDomain): Promise<OrgPolicySet[]>
  upsertPolicySet(payload: PolicySetPayload): Promise<OrgPolicySet>
  resolvePolicy(params: {
    organizationId: string
    domain: PolicyDomain
    workspaceId?: string
    projectId?: string
    objectId?: string
  }): Promise<ResolvedPolicy>
  audit(params?: {
    organizationId?: string
    action?: AuditAction
    actorId?: string
    limit?: number
  }): Promise<AuditRecord[]>
  auditRecord(id: string): Promise<AuditRecord | undefined>
  identities(): Promise<OrgIdentity[]>
  createIdentity(payload: {
    subject: string
    displayName: string
    email?: string
  }): Promise<OrgIdentity>
  identityProviders(): Promise<IdentityProviderStatus[]>
}

export const organizationService: OrganizationService = {
  async list(identityId) {
    return getAtlasProvider().listOrganizations(identityId)
  },
  async get(id) {
    return getAtlasProvider().getOrganization(id)
  },
  async create(payload) {
    return getAtlasProvider().createOrganization(payload)
  },
  async update(id, changes) {
    return getAtlasProvider().updateOrganization(id, changes)
  },
  async members(id) {
    return getAtlasProvider().listOrganizationMembers(id)
  },
  async addMember(id, payload) {
    return getAtlasProvider().addOrganizationMember(id, payload)
  },
  async removeMember(organizationId, membershipId) {
    return getAtlasProvider().removeOrganizationMember(organizationId, membershipId)
  },
  async resolvePermissions(organizationId, identityId) {
    return getAtlasProvider().resolveIdentityPermissions(organizationId, identityId)
  },
  async assignWorker(organizationId, workerId) {
    return getAtlasProvider().assignWorkerToOrganization(organizationId, workerId)
  },
  async roles(organizationId) {
    return getAtlasProvider().listOrgRoles(organizationId)
  },
  async createRole(payload) {
    return getAtlasProvider().createOrgRole(payload)
  },
  async updateRole(roleId, permissions) {
    return getAtlasProvider().updateOrgRole(roleId, permissions)
  },
  async permissions() {
    return getAtlasProvider().listOrgPermissions()
  },
  async teams(organizationId) {
    return getAtlasProvider().listOrgTeams(organizationId)
  },
  async createTeam(payload) {
    return getAtlasProvider().createOrgTeam(payload)
  },
  async policySets(organizationId, domain) {
    return getAtlasProvider().listPolicySets(organizationId, domain)
  },
  async upsertPolicySet(payload) {
    return getAtlasProvider().upsertPolicySet(payload)
  },
  async resolvePolicy(params) {
    return getAtlasProvider().resolvePolicy(params)
  },
  async audit(params) {
    return getAtlasProvider().listAuditRecords(params)
  },
  async auditRecord(id) {
    return getAtlasProvider().getAuditRecord(id)
  },
  async identities() {
    return getAtlasProvider().listIdentities()
  },
  async createIdentity(payload) {
    return getAtlasProvider().createIdentity(payload)
  },
  async identityProviders() {
    return getAtlasProvider().listIdentityProviders()
  },
}
