import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { openExternal } from '../../api/shell'
import { useOnboardingStore, applyTheme } from '../../stores/onboardingStore'
import type {
  DemoSummary,
  OnboardingStepId,
  ThemeChoice,
} from '../../services/OnboardingService'

/**
 * First run.
 *
 * Seven screens, each of which does something real: the workspace step creates
 * a workspace, the diagnostics step records consent, the demo step installs
 * genuine projects. Nothing here is a picture of a feature.
 *
 * Every step can be skipped, and skipping is recorded rather than pretended
 * away — the difference between "finished setup" and "left early" stays
 * visible in the record.
 */

const STEP_LABELS: Record<OnboardingStepId, string> = {
  welcome: 'Welcome',
  workspace: 'Workspace',
  data_location: 'Storage',
  theme: 'Appearance',
  diagnostics: 'Privacy',
  providers: 'Providers',
  demos: 'Examples',
  done: 'Done',
}

const ORDER: OnboardingStepId[] = [
  'welcome',
  'workspace',
  'data_location',
  'theme',
  'diagnostics',
  'providers',
  'demos',
]

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

function StepShell({
  title,
  lede,
  children,
  footer,
}: {
  title: string
  lede: string
  children?: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto px-10 py-12">
        <div className="mx-auto max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-tight text-slate-50">{title}</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-slate-400">{lede}</p>
          <div className="mt-10">{children}</div>
        </div>
      </div>
      <div className="border-t border-slate-800/80 bg-slate-950/60 px-10 py-5">
        <div className="mx-auto flex max-w-2xl items-center justify-between gap-4">{footer}</div>
      </div>
    </div>
  )
}

function PrimaryButton({
  children,
  onClick,
  disabled,
  busy,
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
  busy?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-2.5 text-sm font-medium text-slate-950 transition hover:bg-cyan-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {busy && (
        <span
          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-950/30 border-t-slate-950"
          aria-hidden
        />
      )}
      {children}
    </button>
  )
}

function TextButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md px-2 py-1 text-sm text-slate-400 transition hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-600"
    >
      {children}
    </button>
  )
}

function Choice({
  selected,
  onSelect,
  title,
  description,
  badge,
}: {
  selected: boolean
  onSelect: () => void
  title: string
  description: string
  badge?: string
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={
        'w-full rounded-xl border p-4 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ' +
        (selected
          ? 'border-cyan-400/60 bg-cyan-400/10'
          : 'border-slate-800 bg-slate-900/40 hover:border-slate-700')
      }
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-slate-100">{title}</span>
        {badge && (
          <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400">
            {badge}
          </span>
        )}
      </div>
      <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{description}</p>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------------

function Welcome({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  return (
    <StepShell
      title="Welcome to Atlas"
      lede="Atlas runs AI work on your own machine — writing, research, images, video and the automation that ties them together. Setup takes about a minute, and you can change any of it later."
      footer={
        <>
          <TextButton onClick={onSkip}>Skip setup</TextButton>
          <PrimaryButton onClick={onNext}>Get started</PrimaryButton>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          {
            title: 'Yours alone',
            body: 'Your work stays in a database on this machine. Nothing is uploaded, and there is no account.',
          },
          {
            title: 'Nothing runs itself',
            body: 'Anything irreversible stops and waits for you. Atlas never publishes or deletes on its own.',
          },
          {
            title: 'Bring your own models',
            body: 'Connect the providers you already pay for, or run models locally. Atlas is the coordinator.',
          },
        ].map((card) => (
          <div key={card.title} className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <h3 className="text-sm font-medium text-slate-100">{card.title}</h3>
            <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{card.body}</p>
          </div>
        ))}
      </div>
    </StepShell>
  )
}

function Workspace({
  onCreate,
  onSkip,
  busy,
}: {
  onCreate: (name: string, description: string) => void
  onSkip: () => void
  busy: boolean
}) {
  const [name, setName] = useState('My Workspace')
  const [description, setDescription] = useState('')
  const valid = name.trim().length > 0

  return (
    <StepShell
      title="Create a workspace"
      lede="A workspace holds related projects, assets and automations. Most people start with one and add more when the work genuinely separates."
      footer={
        <>
          <TextButton onClick={onSkip}>Do this later</TextButton>
          <PrimaryButton
            onClick={() => onCreate(name.trim(), description.trim())}
            disabled={!valid}
            busy={busy}
          >
            Create workspace
          </PrimaryButton>
        </>
      }
    >
      <div className="space-y-5">
        <div>
          <label htmlFor="ws-name" className="block text-sm font-medium text-slate-200">
            Name
          </label>
          <input
            id="ws-name"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && valid) onCreate(name.trim(), description.trim())
            }}
            className="mt-2 w-full rounded-lg border border-slate-800 bg-slate-900/60 px-3.5 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-400/60"
            placeholder="My Workspace"
          />
          {!valid && <p className="mt-2 text-xs text-amber-400/80">A workspace needs a name.</p>}
        </div>
        <div>
          <label htmlFor="ws-desc" className="block text-sm font-medium text-slate-200">
            What is it for? <span className="font-normal text-slate-500">Optional</span>
          </label>
          <input
            id="ws-desc"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="mt-2 w-full rounded-lg border border-slate-800 bg-slate-900/60 px-3.5 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-400/60"
            placeholder="Client work, personal projects, research…"
          />
        </div>
      </div>
    </StepShell>
  )
}

function DataLocation({
  directory,
  onNext,
}: {
  directory: string | null
  onNext: () => void
}) {
  return (
    <StepShell
      title="Where your work is kept"
      lede="Atlas stores everything locally, in its own database. This is the folder it uses."
      footer={<PrimaryButton onClick={onNext}>Continue</PrimaryButton>}
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Data folder</div>
          <div className="mt-2 break-all font-mono text-[13px] text-slate-200">
            {directory ?? 'The default location for this operating system'}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800/70 bg-slate-900/20 p-4">
          <h3 className="text-sm font-medium text-slate-200">Moving it later</h3>
          <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
            Set <code className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[12px]">ATLAS_DATA_DIR</code>{' '}
            to keep everything beside the application instead — useful on a portable drive. Back up this
            folder and you have backed up Atlas.
          </p>
        </div>
      </div>
    </StepShell>
  )
}

function Appearance({
  theme,
  onChoose,
  onNext,
}: {
  theme: ThemeChoice
  onChoose: (theme: ThemeChoice) => void
  onNext: () => void
}) {
  return (
    <StepShell
      title="Appearance"
      lede="Atlas is built for long sessions. Pick what is comfortable — this changes immediately and you can switch whenever."
      footer={<PrimaryButton onClick={onNext}>Continue</PrimaryButton>}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Choice
          selected={theme === 'dark'}
          onSelect={() => onChoose('dark')}
          title="Dark"
          description="The default. Easier on the eyes for long stretches."
        />
        <Choice
          selected={theme === 'light'}
          onSelect={() => onChoose('light')}
          title="Light"
          description="Better in a bright room or for screen sharing."
        />
        <Choice
          selected={theme === 'system'}
          onSelect={() => onChoose('system')}
          title="Match system"
          description="Follows your operating system, including when it switches at sunset."
        />
      </div>
    </StepShell>
  )
}

function Diagnostics({
  onChoose,
  busy,
}: {
  onChoose: (mode: 'disabled' | 'crash_only' | 'diagnostics') => void
  busy: boolean
}) {
  const [mode, setMode] = useState<'disabled' | 'crash_only' | 'diagnostics'>('disabled')

  return (
    <StepShell
      title="Diagnostics"
      lede="Atlas collects nothing by default, and there is no Atlas server for it to send anything to. If you turn this on, reports are written to a file on this machine that you can read."
      footer={
        <>
          <span className="text-xs text-slate-500">You can change this any time in Settings.</span>
          <PrimaryButton onClick={() => onChoose(mode)} busy={busy}>
            Continue
          </PrimaryButton>
        </>
      }
    >
      <div className="space-y-3">
        <Choice
          selected={mode === 'disabled'}
          onSelect={() => setMode('disabled')}
          title="Collect nothing"
          description="No crash reports, no usage data. This is the default."
          badge="Default"
        />
        <Choice
          selected={mode === 'crash_only'}
          onSelect={() => setMode('crash_only')}
          title="Crash reports only"
          description="The type of error and where in Atlas it happened. Never the error message, which can contain file paths and your own text."
        />
        <Choice
          selected={mode === 'diagnostics'}
          onSelect={() => setMode('diagnostics')}
          title="Crashes and version"
          description="The above, plus which version of Atlas and which operating system. Helps prioritise what to fix."
        />

        <div className="rounded-xl border border-slate-800/70 bg-slate-900/20 p-4">
          <h3 className="text-sm font-medium text-slate-200">What is never collected</h3>
          <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
            Your prompts, files, project names, assets and provider keys. This is enforced by an
            allow-list of permitted fields in the code, not by a policy — a field cannot be collected
            until someone deliberately adds it to that list.
          </p>
        </div>
      </div>
    </StepShell>
  )
}

const PROVIDERS = [
  {
    id: 'anthropic',
    name: 'Anthropic',
    use: 'Writing, research and reasoning',
    url: 'https://console.anthropic.com/settings/keys',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    use: 'Writing, images and speech',
    url: 'https://platform.openai.com/api-keys',
  },
  {
    id: 'google',
    name: 'Google AI',
    use: 'Long documents and video understanding',
    url: 'https://aistudio.google.com/apikey',
  },
  {
    id: 'local',
    name: 'Local models',
    use: 'Runs on your own GPU. No key, no cost, no network.',
    url: null,
  },
]

function Providers({
  selected,
  onToggle,
  onNext,
  onSkip,
}: {
  selected: string[]
  onToggle: (id: string) => void
  onNext: () => void
  onSkip: () => void
}) {
  return (
    <StepShell
      title="Connect a model provider"
      lede="Atlas coordinates models, it does not include them. Tell it which providers you intend to use and it will ask for the key when you first need it — nothing is stored now."
      footer={
        <>
          <TextButton onClick={onSkip}>I will do this later</TextButton>
          <PrimaryButton onClick={onNext}>Continue</PrimaryButton>
        </>
      }
    >
      <div className="space-y-3">
        {PROVIDERS.map((provider) => (
          <div
            key={provider.id}
            className={
              'rounded-xl border p-4 transition ' +
              (selected.includes(provider.id)
                ? 'border-cyan-400/60 bg-cyan-400/10'
                : 'border-slate-800 bg-slate-900/40')
            }
          >
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-100">{provider.name}</div>
                <p className="mt-1 text-[13px] text-slate-400">{provider.use}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {provider.url && (
                  <button
                    type="button"
                    onClick={() => openExternal(provider.url as string)}
                    className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 transition hover:border-slate-500"
                  >
                    Get a key
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => onToggle(provider.id)}
                  aria-pressed={selected.includes(provider.id)}
                  className={
                    'rounded-md px-3 py-1 text-xs font-medium transition ' +
                    (selected.includes(provider.id)
                      ? 'bg-cyan-400 text-slate-950'
                      : 'border border-slate-700 text-slate-300 hover:border-slate-500')
                  }
                >
                  {selected.includes(provider.id) ? 'Selected' : 'Select'}
                </button>
              </div>
            </div>
          </div>
        ))}

        <p className="pt-1 text-[13px] leading-relaxed text-slate-500">
          Atlas works without any of these. Automation, approvals, the knowledge graph and scheduling
          need no provider at all.
        </p>
      </div>
    </StepShell>
  )
}

function Demos({
  demos,
  installed,
  installing,
  onInstall,
  onFinish,
}: {
  demos: DemoSummary[]
  installed: Record<string, { project_id: string; notes: string[] }>
  installing: string | null
  onInstall: (id: string) => void
  onFinish: () => void
}) {
  const anyInstalled = Object.keys(installed).length > 0

  return (
    <StepShell
      title="Start with a real example"
      lede="Each of these installs a genuine project — real automation rules, a real knowledge graph — that you can open, change or delete. They are not demonstrations of features; they are the features."
      footer={
        <>
          <span className="text-xs text-slate-500">
            {anyInstalled
              ? `${Object.keys(installed).length} installed. They are in your projects list.`
              : 'Optional. You can install these later from Help.'}
          </span>
          <PrimaryButton onClick={onFinish}>
            {anyInstalled ? 'Open Atlas' : 'Skip and open Atlas'}
          </PrimaryButton>
        </>
      }
    >
      {demos.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 text-center">
          <p className="text-sm text-slate-400">
            The example catalogue could not be loaded. This does not affect anything else — you can
            install examples later from the Help menu.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {demos.map((demo) => {
            const done = Boolean(installed[demo.id])
            const busy = installing === demo.id
            return (
              <div
                key={demo.id}
                className={
                  'rounded-xl border p-4 transition ' +
                  (done ? 'border-cyan-400/40 bg-cyan-400/5' : 'border-slate-800 bg-slate-900/40')
                }
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 gap-3">
                    <span className="text-xl leading-none" aria-hidden>
                      {demo.icon}
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-medium text-slate-100">{demo.name}</h3>
                        {demo.runs_fully_offline ? (
                          <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300">
                            Runs without a provider
                          </span>
                        ) : (
                          <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400">
                            {demo.offline_step_count} of {demo.step_count} steps run now
                          </span>
                        )}
                        {demo.has_approval_gate && (
                          <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400">
                            Approval gate
                          </span>
                        )}
                      </div>
                      <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
                        {demo.tagline}
                      </p>
                      {done && installed[demo.id].notes.length > 0 && (
                        <ul className="mt-2.5 space-y-1">
                          {installed[demo.id].notes.map((note) => (
                            <li key={note} className="text-[12px] leading-relaxed text-cyan-200/70">
                              {note}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => onInstall(demo.id)}
                    disabled={done || busy}
                    className={
                      'shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition ' +
                      (done
                        ? 'cursor-default border border-cyan-400/40 text-cyan-300'
                        : 'border border-slate-700 text-slate-200 hover:border-slate-500 disabled:opacity-50')
                    }
                  >
                    {done ? 'Installed' : busy ? 'Installing…' : 'Install'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </StepShell>
  )
}

// ---------------------------------------------------------------------------
// Flow
// ---------------------------------------------------------------------------

export function OnboardingFlow({ onDone }: { onDone: () => void }) {
  const store = useOnboardingStore()
  const [providers, setProviders] = useState<string[]>([])
  const [dataDir, setDataDir] = useState<string | null>(null)

  const step = store.state?.current_step ?? 'welcome'
  const busy = store.phase === 'working'

  useEffect(() => {
    if (store.state?.completed) onDone()
  }, [store.state?.completed, onDone])

  useEffect(() => {
    // Shown on the storage step. A failure here is not worth interrupting
    // setup for — the screen falls back to describing the default location.
    import('../../services/OnboardingService')
      .then(({ onboardingService }) => onboardingService.configuration())
      .then((config) => setDataDir(config.data_dir ?? null))
      .catch(() => setDataDir(null))
  }, [])

  const completed = useMemo(
    () => new Set(store.state?.completed_steps ?? []),
    [store.state?.completed_steps],
  )

  if (!store.state) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <span className="text-sm text-slate-500">Loading setup…</span>
      </div>
    )
  }

  const body = (() => {
    switch (step) {
      case 'welcome':
        return <Welcome onNext={() => store.completeStep('welcome')} onSkip={store.skip} />
      case 'workspace':
        return (
          <Workspace
            busy={busy}
            onCreate={(name, description) => store.createWorkspace(name, description)}
            onSkip={() => store.completeStep('workspace')}
          />
        )
      case 'data_location':
        return (
          <DataLocation
            directory={dataDir}
            onNext={() =>
              store.completeStep('data_location', dataDir ? { data_directory: dataDir } : {})
            }
          />
        )
      case 'theme':
        return (
          <Appearance
            theme={store.state?.theme ?? 'dark'}
            onChoose={(theme) => applyTheme(theme)}
            onNext={() => store.setTheme(store.state?.theme ?? 'dark')}
          />
        )
      case 'diagnostics':
        return <Diagnostics busy={busy} onChoose={(mode) => store.setTelemetry(mode)} />
      case 'providers':
        return (
          <Providers
            selected={providers}
            onToggle={(id) =>
              setProviders((current) =>
                current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
              )
            }
            onNext={() => store.completeStep('providers', { configured_providers: providers })}
            onSkip={() => store.completeStep('providers')}
          />
        )
      case 'demos':
        return (
          <Demos
            demos={store.demos}
            installed={store.installed}
            installing={store.installing}
            onInstall={(id) => store.installDemo(id)}
            onFinish={() => store.completeStep('demos')}
          />
        )
      default:
        return null
    }
  })()

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <aside className="hidden w-64 shrink-0 border-r border-slate-800/80 bg-slate-950 px-6 py-12 lg:block">
        <div className="mb-10 flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-800 text-xs font-semibold text-cyan-300">
            A
          </span>
          <span className="text-sm font-medium text-slate-200">Atlas</span>
        </div>

        <ol className="space-y-1">
          {ORDER.map((id, index) => {
            const isDone = completed.has(id)
            const isCurrent = id === step
            return (
              <li key={id}>
                <div
                  aria-current={isCurrent ? 'step' : undefined}
                  className={
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ' +
                    (isCurrent
                      ? 'bg-slate-900 text-slate-100'
                      : isDone
                        ? 'text-slate-400'
                        : 'text-slate-600')
                  }
                >
                  <span
                    className={
                      'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] ' +
                      (isDone
                        ? 'border-cyan-400/50 bg-cyan-400/15 text-cyan-300'
                        : isCurrent
                          ? 'border-slate-500 text-slate-200'
                          : 'border-slate-800 text-slate-600')
                    }
                  >
                    {isDone ? '✓' : index + 1}
                  </span>
                  {STEP_LABELS[id]}
                </div>
              </li>
            )
          })}
        </ol>
      </aside>

      <main className="flex-1">
        {store.error && (
          <div
            role="alert"
            className="flex items-center justify-between gap-4 border-b border-amber-500/30 bg-amber-500/10 px-10 py-3 text-sm text-amber-200"
          >
            <span>{store.error}</span>
            <button
              type="button"
              onClick={store.clearError}
              className="rounded px-2 py-0.5 text-xs text-amber-200/80 transition hover:text-amber-100"
            >
              Dismiss
            </button>
          </div>
        )}
        {body}
      </main>
    </div>
  )
}
