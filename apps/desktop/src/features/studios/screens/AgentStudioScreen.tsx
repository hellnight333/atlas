import { useEffect, useMemo, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useAgentStore, useAssetStore, useProjectStore } from '../../../stores'

const permissionOptions = [
  'read_assets',
  'write_assets',
  'execute_workflow',
  'review_assets',
  'publish_assets',
  'delete_assets',
  'modify_project',
  'manage_agents',
] as const

export function AgentStudioScreen() {
  const projects = useProjectStore((state) => state.projects)
  const project = projects[0]
  const assets = useAssetStore((state) => state.assets)

  const agents = useAgentStore((state) => state.agents)
  const activeAgent = useAgentStore((state) => state.activeAgent)
  const memoryRefs = useAgentStore((state) => state.memoryRefs)
  const permissions = useAgentStore((state) => state.permissions)
  const loadAgents = useAgentStore((state) => state.loadAgents)
  const createAgent = useAgentStore((state) => state.createAgent)
  const updateAgent = useAgentStore((state) => state.updateAgent)
  const deleteAgent = useAgentStore((state) => state.deleteAgent)
  const attachMemory = useAgentStore((state) => state.attachMemory)
  const setActiveAgent = useAgentStore((state) => state.setActiveAgent)
  const latestPlan = useAgentStore((state) => state.latestPlan)
  const generatePlan = useAgentStore((state) => state.generatePlan)
  const latestSchedule = useAgentStore((state) => state.latestSchedule)
  const scheduleQueue = useAgentStore((state) => state.scheduleQueue)
  const createSchedule = useAgentStore((state) => state.createSchedule)
  const pauseSchedule = useAgentStore((state) => state.pauseSchedule)
  const resumeSchedule = useAgentStore((state) => state.resumeSchedule)
  const cancelSchedule = useAgentStore((state) => state.cancelSchedule)
  const runtimeExecutions = useAgentStore((state) => state.runtimeExecutions)
  const runningExecutions = useAgentStore((state) => state.runningExecutions)
  const runtimeHistory = useAgentStore((state) => state.runtimeHistory)
  const selectedRuntimeExecution = useAgentStore((state) => state.selectedRuntimeExecution)
  const startRuntimeSchedule = useAgentStore((state) => state.startRuntimeSchedule)
  const loadRuntime = useAgentStore((state) => state.loadRuntime)
  const cancelRuntimeExecution = useAgentStore((state) => state.cancelRuntimeExecution)
  const retryRuntimeExecution = useAgentStore((state) => state.retryRuntimeExecution)
  const activeTeam = useAgentStore((state) => state.activeTeam)
  const teamMessages = useAgentStore((state) => state.teamMessages)
  const teamStatus = useAgentStore((state) => state.teamStatus)
  const createTeam = useAgentStore((state) => state.createTeam)
  const loadTeam = useAgentStore((state) => state.loadTeam)
  const cancelTeam = useAgentStore((state) => state.cancelTeam)

  const [name, setName] = useState('Atlas Agent')
  const [role, setRole] = useState('operator')
  const [description, setDescription] = useState('')
  const [goal, setGoal] = useState('Create an execution-ready plan for the current project goals')
  const [teamName, setTeamName] = useState('Launch Team')

  useEffect(() => {
    void loadAgents(project?.id)
  }, [loadAgents, project?.id])

  useEffect(() => {
    void loadRuntime()
  }, [loadRuntime])

  useEffect(() => {
    if (activeTeam?.id) {
      void loadTeam(activeTeam.id)
    }
  }, [activeTeam?.id, loadTeam])

  const selectedAssetId = useMemo(() => assets[0]?.id ?? '', [assets])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
      <Panel title="Agent List" subtitle="Create and select agents">
        <div className="space-y-3">
          <input
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Agent name"
          />
          <input
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={role}
            onChange={(event) => setRole(event.target.value)}
            placeholder="Agent role"
          />
          <textarea
            className="min-h-16 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Description"
          />
          <Button
            onClick={() => {
              if (!project || !name.trim() || !role.trim()) {
                return
              }
              void createAgent({
                name,
                role,
                description,
                projectId: project.id,
                status: 'idle',
                capabilities: [],
                permissionSet: ['read_assets'],
              })
            }}
          >
            Create Agent
          </Button>
          <div className="space-y-2">
            {agents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                className={`block w-full rounded px-3 py-2 text-left text-sm ${activeAgent?.id === agent.id ? 'bg-emerald-500/15 text-emerald-100' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'}`}
                onClick={() => setActiveAgent(agent)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{agent.name}</span>
                  <span className="text-xs uppercase tracking-widest text-slate-500">{agent.status}</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{agent.role}</p>
              </button>
            ))}
          </div>
        </div>
      </Panel>

      <Panel title="Agent Inspector" subtitle="Status, permissions, memory, and timeline placeholder">
        <div className="space-y-4">
          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <h4 className="text-sm font-medium text-slate-100">Goal Editor</h4>
            <textarea
              className="mt-2 min-h-20 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder="Describe the goal for planning"
            />
            <div className="mt-2 flex items-center justify-between">
              <p className="text-xs text-slate-400">Planner produces plan only. No workflow execution in 006B.</p>
              <Button
                variant="accent"
                onClick={() => {
                  if (!activeAgent || !goal.trim()) {
                    return
                  }
                  void generatePlan(activeAgent.id, goal)
                }}
              >
                Generate Plan
              </Button>
            </div>
          </div>

          <div className="grid gap-2 rounded border border-slate-700 bg-slate-950 p-3 md:grid-cols-2">
            <Button
              variant="accent"
              onClick={() => {
                if (!activeAgent) {
                  return
                }
                void updateAgent(activeAgent.id, { status: 'planning' })
              }}
            >
              Set Planning
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (!activeAgent) {
                  return
                }
                void updateAgent(activeAgent.id, { status: 'paused' })
              }}
            >
              Pause
            </Button>
            <Button
              onClick={() => {
                if (!activeAgent || !selectedAssetId) {
                  return
                }
                void attachMemory(activeAgent.id, 'workspace', selectedAssetId)
              }}
            >
              Attach Memory
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (!activeAgent) {
                  return
                }
                void deleteAgent(activeAgent.id)
              }}
            >
              Delete Agent
            </Button>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <h4 className="text-sm font-medium text-slate-100">Permissions</h4>
            <div className="mt-2 flex flex-wrap gap-2">
              {permissionOptions.map((permission) => (
                <span
                  key={permission}
                  className={`rounded px-2 py-1 text-xs ${permissions.includes(permission) ? 'bg-emerald-500/20 text-emerald-100' : 'bg-slate-900 text-slate-500'}`}
                >
                  {permission}
                </span>
              ))}
            </div>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <h4 className="text-sm font-medium text-slate-100">Memory References</h4>
            <ul className="mt-2 space-y-2 text-sm text-slate-300">
              {memoryRefs.map((reference) => (
                <li key={reference.id} className="rounded bg-slate-900 px-3 py-2">
                  <div className="text-xs uppercase tracking-widest text-slate-500">{reference.kind}</div>
                  <div className="mt-1 text-slate-100">{reference.asset_id}</div>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <h4 className="text-sm font-medium text-slate-100">Generated Plan</h4>
            {latestPlan ? (
              <div className="mt-2 space-y-3 text-sm text-slate-300">
                <div className="grid gap-2 md:grid-cols-2">
                  <div className="rounded bg-slate-900 px-3 py-2">
                    <div className="text-xs uppercase tracking-widest text-slate-500">Confidence</div>
                    <div className="mt-1 text-slate-100">{Math.round(latestPlan.confidence * 100)}%</div>
                  </div>
                  <div className="rounded bg-slate-900 px-3 py-2">
                    <div className="text-xs uppercase tracking-widest text-slate-500">Estimated Cost</div>
                    <div className="mt-1 text-slate-100">${latestPlan.estimated_cost_usd.toFixed(4)}</div>
                  </div>
                </div>

                <div className="rounded bg-slate-900 px-3 py-2">
                  <div className="text-xs uppercase tracking-widest text-slate-500">Step Tree</div>
                  <ul className="mt-2 space-y-2">
                    {latestPlan.steps.map((step) => (
                      <li key={step.id} className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        <div className="font-medium text-slate-100">{step.description}</div>
                        <div className="mt-1 text-xs text-slate-400">
                          Capability: {step.capability} | Action: {step.action} | Time: {step.estimated_time_seconds}s | Cost: ${step.estimated_cost_usd.toFixed(4)}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          Dependencies: {step.dependencies.length > 0 ? step.dependencies.join(', ') : 'none'}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          Execution Preview: {step.estimate.provider_class}, {step.estimate.tokens} tokens, {step.estimate.gpu_seconds}s GPU
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="rounded bg-slate-900 px-3 py-2">
                  <div className="text-xs uppercase tracking-widest text-slate-500">Scheduler</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button
                      variant="accent"
                      onClick={() => {
                        if (!activeAgent || !goal.trim()) {
                          return
                        }
                        void createSchedule(activeAgent.id, goal, 'normal')
                      }}
                    >
                      Build Schedule
                    </Button>
                    <Button
                      onClick={() => {
                        if (!latestSchedule) {
                          return
                        }
                        void startRuntimeSchedule(latestSchedule.schedule_id)
                      }}
                    >
                      Start Runtime
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        if (!latestSchedule) {
                          return
                        }
                        void pauseSchedule(latestSchedule.schedule_id)
                      }}
                    >
                      Pause
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        if (!latestSchedule) {
                          return
                        }
                        void resumeSchedule(latestSchedule.schedule_id)
                      }}
                    >
                      Resume
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        if (!latestSchedule) {
                          return
                        }
                        void cancelSchedule(latestSchedule.schedule_id)
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  <div className="rounded bg-slate-900 px-3 py-2">
                    <div className="text-xs uppercase tracking-widest text-slate-500">Dependencies</div>
                    <div className="mt-1 text-xs text-slate-300">
                      {latestPlan.dependencies.length > 0
                        ? latestPlan.dependencies.map((edge) => `${edge.from} -> ${edge.to}`).join(' | ')
                        : 'none'}
                    </div>
                  </div>
                  <div className="rounded bg-slate-900 px-3 py-2">
                    <div className="text-xs uppercase tracking-widest text-slate-500">Review Points</div>
                    <div className="mt-1 text-xs text-slate-300">
                      {latestPlan.review_required ? 'Review required before execution handoff.' : 'No explicit review gate.'}
                    </div>
                  </div>
                </div>

                <div className="rounded bg-slate-900 px-3 py-2">
                  <div className="text-xs uppercase tracking-widest text-slate-500">Scheduler Queue</div>
                  {latestSchedule ? (
                    <div className="mt-2 space-y-2 text-xs text-slate-300">
                      <div className="grid gap-2 md:grid-cols-2">
                        <div className="rounded border border-slate-700 bg-slate-950 px-2 py-1">
                          Schedule: {latestSchedule.schedule_id}
                        </div>
                        <div className="rounded border border-slate-700 bg-slate-950 px-2 py-1">
                          Priority: {latestSchedule.priority}
                        </div>
                      </div>
                      <div className="rounded border border-slate-700 bg-slate-950 px-2 py-2">
                        <div>Parallel groups: {latestSchedule.parallel_groups.map((group) => `[${group.join(', ')}]`).join(' ') || 'none'}</div>
                        <div className="mt-1">Blocked entries: {latestSchedule.blocked_entries.join(', ') || 'none'}</div>
                        <div className="mt-1">Resume tokens: {latestSchedule.resume_tokens.length}</div>
                      </div>
                      <ul className="space-y-2">
                        {scheduleQueue.map((entry) => (
                          <li key={entry.id} className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-slate-100">{entry.plan_step.description}</span>
                              <span className="uppercase tracking-widest text-slate-400">{entry.status}</span>
                            </div>
                            <div className="mt-1 text-slate-400">
                              Priority: {entry.priority} | Capability: {entry.capability} | Retry: {entry.retry_count}
                            </div>
                            <div className="mt-1 text-slate-500">
                              Dependencies: {entry.dependencies.length ? entry.dependencies.join(', ') : 'none'}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-slate-500">No schedule created yet.</p>
                  )}
                </div>

                <div className="rounded bg-slate-900 px-3 py-2">
                  <div className="text-xs uppercase tracking-widest text-slate-500">Execution Queue</div>
                  <div className="mt-2 text-xs text-slate-300">
                    Running: {runningExecutions.length} | Total: {runtimeExecutions.length} | History: {runtimeHistory.length}
                  </div>
                  {runtimeExecutions.length > 0 ? (
                    <ul className="mt-2 space-y-2">
                      {runtimeExecutions.map((execution) => (
                        <li key={execution.execution_id} className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-300">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-slate-100">{execution.action}</span>
                            <span className="uppercase tracking-widest text-slate-400">{execution.status}</span>
                          </div>
                          <div className="mt-1">Attempts: {execution.attempts} | Provider: {execution.provider_name ?? 'pending'}</div>
                          <div className="mt-1">Job: {execution.job_id ?? 'pending'} | Asset: {execution.asset_id ?? 'pending'}</div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Button
                              variant="ghost"
                              onClick={() => {
                                void cancelRuntimeExecution(execution.execution_id)
                              }}
                            >
                              Cancel
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                void retryRuntimeExecution(execution.execution_id)
                              }}
                            >
                              Retry
                            </Button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs text-slate-500">No runtime executions yet.</p>
                  )}
                </div>

                <div className="rounded bg-slate-900 px-3 py-2">
                  <div className="text-xs uppercase tracking-widest text-slate-500">Team View</div>
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    <input
                      className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                      value={teamName}
                      onChange={(event) => setTeamName(event.target.value)}
                      placeholder="Team name"
                    />
                    <Button
                      onClick={() => {
                        const teamAssignments = agents.slice(0, 5).map((agent, index) => ({
                          agentId: agent.id,
                          role: (agent.role as 'research' | 'planner' | 'writer' | 'reviewer' | 'image' | 'video' | 'developer' | 'operator'),
                          title: `${agent.role} assignment`,
                          action: agent.role === 'image' || agent.role === 'video' ? 'image.generate' : agent.role === 'developer' ? 'code.generate' : 'text.generate',
                          payload: { prompt: `${agent.role} collaboration task` },
                          dependencies: index === 0 ? [] : [agents[0]?.id ?? ''],
                        }))
                        void createTeam(teamName, teamAssignments)
                      }}
                    >
                      Create Team
                    </Button>
                  </div>
                  {activeTeam ? (
                    <div className="mt-3 space-y-3 text-xs text-slate-300">
                      <div className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        Team: {activeTeam.name} | Status: {activeTeam.status}
                      </div>
                      <div className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        Waiting Agents: {teamStatus?.waiting.join(', ') || 'none'}
                      </div>
                      <div className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        Completed Agents: {teamStatus?.completed.join(', ') || 'none'}
                      </div>
                      <div className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        <div className="text-xs uppercase tracking-widest text-slate-500">Agent Graph</div>
                        <div className="mt-2 whitespace-pre-wrap text-slate-300">{activeTeam.assignments.map((assignment) => `${assignment.role} -> ${assignment.dependencies.join(', ') || 'start'}`).join('\n')}</div>
                      </div>
                      <div className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        <div className="text-xs uppercase tracking-widest text-slate-500">Execution Flow</div>
                        <ul className="mt-2 space-y-1">
                          {activeTeam.assignments.map((assignment) => (
                            <li key={assignment.id}>{assignment.title} | {assignment.status} | {assignment.action}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        <div className="text-xs uppercase tracking-widest text-slate-500">Mailbox</div>
                        <ul className="mt-2 space-y-1">
                          {teamMessages.map((message) => (
                            <li key={message.id}>{message.type} | {message.sender} {'->'} {message.receiver}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="rounded border border-slate-700 bg-slate-950 px-3 py-2">
                        <div className="text-xs uppercase tracking-widest text-slate-500">Message Timeline</div>
                        <ul className="mt-2 space-y-1">
                          {teamMessages.map((message) => (
                            <li key={`${message.id}-time`}>{message.timestamp} | {message.type}</li>
                          ))}
                        </ul>
                      </div>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          void cancelTeam(activeTeam.id)
                        }}
                      >
                        Cancel Team
                      </Button>
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-slate-500">No active team collaboration yet.</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="mt-2 text-xs text-slate-500">Generate a plan from a goal to preview steps, dependencies, confidence, and cost.</p>
            )}
          </div>
        </div>
      </Panel>

      <Panel title="Execution Details" subtitle="Running tasks, progress, and timeline">
        <div className="space-y-2 text-sm text-slate-300">
          <p className="rounded bg-slate-900 px-3 py-2">Selected Execution: {selectedRuntimeExecution?.execution_id ?? 'None'}</p>
          <p className="rounded bg-slate-900 px-3 py-2">Status: {selectedRuntimeExecution?.status ?? 'None'}</p>
          <p className="rounded bg-slate-900 px-3 py-2">Progress Heartbeat: {selectedRuntimeExecution?.heartbeat_at ?? 'None'}</p>
          <div className="rounded bg-slate-900 px-3 py-2">
            <div className="text-xs uppercase tracking-widest text-slate-500">Timeline</div>
            <ul className="mt-2 space-y-1 text-xs text-slate-300">
              {(selectedRuntimeExecution?.timeline ?? []).map((item, index) => (
                <li key={`${item.timestamp}-${index}`}>{item.status} @ {item.timestamp}</li>
              ))}
            </ul>
          </div>
        </div>
      </Panel>
    </section>
  )
}
