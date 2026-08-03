import { AtlasApiClient } from '../api/client'

/**
 * Setup state, stored by the kernel.
 *
 * This deliberately does not go through AtlasProvider. Onboarding writes to a
 * real installation and has no meaningful mock: pretending to save a workspace
 * that is never created would be the kind of fake this milestone rules out.
 * When there is no kernel to talk to, setup is reported as already done and the
 * application proceeds.
 */

export type OnboardingStepId =
  | 'welcome'
  | 'workspace'
  | 'data_location'
  | 'theme'
  | 'diagnostics'
  | 'providers'
  | 'demos'
  | 'done'

export type ThemeChoice = 'dark' | 'light' | 'system'

export interface OnboardingState {
  completed: boolean
  current_step: OnboardingStepId
  completed_steps: string[]
  workspace_id: string | null
  workspace_name: string | null
  theme: ThemeChoice
  data_directory: string | null
  configured_providers: string[]
  installed_demos: string[]
  started_at: string | null
  completed_at: string | null
  skipped: boolean
  steps: OnboardingStepId[]
  progress: number
}

export interface DemoStep {
  name: string
  description: string
  requires_provider: boolean
  subsystem: string
}

export interface DemoAutomation {
  name: string
  description: string
  trigger: string
  schedule: string | null
}

export interface DemoSummary {
  id: string
  name: string
  tagline: string
  description: string
  category: string
  icon: string
  demonstrates: string[]
  estimated_minutes: number
  runs_fully_offline: boolean
  step_count: number
  offline_step_count: number
  provider_step_count: number
  automation_count: number
  has_approval_gate: boolean
  steps: DemoStep[]
  automations: DemoAutomation[]
}

export interface DemoInstallResult {
  demo_id: string
  project_id: string
  created: boolean
  automations: string[]
  graph_nodes: string[]
  approval_policy: string | null
  notes: string[]
}

export interface StepPayload {
  workspace_id?: string
  workspace_name?: string
  theme?: ThemeChoice
  data_directory?: string
  configured_providers?: string[]
}

const client = new AtlasApiClient()

/** Used when there is no kernel: the app must still open. */
export const ASSUMED_COMPLETE: OnboardingState = {
  completed: true,
  current_step: 'done',
  completed_steps: [],
  workspace_id: null,
  workspace_name: null,
  theme: 'dark',
  data_directory: null,
  configured_providers: [],
  installed_demos: [],
  started_at: null,
  completed_at: null,
  skipped: false,
  steps: [],
  progress: 1,
}

export const onboardingService = {
  async state(): Promise<OnboardingState> {
    return client.get<OnboardingState>('/api/onboarding')
  },

  async completeStep(step: OnboardingStepId, payload: StepPayload = {}): Promise<OnboardingState> {
    return client.post<OnboardingState>(`/api/onboarding/step/${step}`, payload)
  },

  async skip(): Promise<OnboardingState> {
    return client.post<OnboardingState>('/api/onboarding/skip')
  },

  async reset(): Promise<OnboardingState> {
    return client.post<OnboardingState>('/api/onboarding/reset')
  },

  async createWorkspace(name: string, description: string): Promise<{ workspace_id: string }> {
    return client.post<{ workspace_id: string }>('/api/workspaces', { name, description })
  },

  async demos(): Promise<DemoSummary[]> {
    return client.get<DemoSummary[]>('/api/demos')
  },

  async installDemo(demoId: string): Promise<DemoInstallResult> {
    return client.post<DemoInstallResult>(`/api/demos/${demoId}/install`)
  },

  async configuration(): Promise<{ data_dir?: string; profile?: string }> {
    return client.get<{ data_dir?: string; profile?: string }>('/api/configuration')
  },

  async setTelemetry(mode: 'disabled' | 'crash_only' | 'diagnostics'): Promise<unknown> {
    return client.put<unknown>('/api/telemetry/consent', { mode })
  },
}
