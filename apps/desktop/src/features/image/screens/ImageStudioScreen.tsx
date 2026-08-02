import { useEffect, useMemo, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useImageStore, useProjectStore, useReviewStore } from '../../../stores'

export function ImageStudioScreen() {
  const projects = useProjectStore((state) => state.projects)
  const activeProjectId = projects[0]?.id ?? 'p1'

  const images = useImageStore((state) => state.images)
  const selectedImageId = useImageStore((state) => state.selectedImageId)
  const status = useImageStore((state) => state.status)
  const error = useImageStore((state) => state.error)
  const versions = useImageStore((state) => state.versions)
  const loadImages = useImageStore((state) => state.loadImages)
  const loadImageVersions = useImageStore((state) => state.loadImageVersions)
  const generateImage = useImageStore((state) => state.generateImage)
  const createVariant = useImageStore((state) => state.createVariant)
  const regenerateImage = useImageStore((state) => state.regenerateImage)
  const setSelectedImageId = useImageStore((state) => state.setSelectedImageId)

  const createReviewSession = useReviewStore((state) => state.createSession)

  const [prompt, setPrompt] = useState('Editorial hero shot of a mobile product floating over brushed aluminum, cinematic side light')
  const [negativePrompt, setNegativePrompt] = useState('blurry, noisy, text artifacts, watermark')
  const [styles, setStyles] = useState('editorial, high contrast')
  const [resolution, setResolution] = useState('1024x1024')
  const [seed, setSeed] = useState('')
  const [steps, setSteps] = useState('30')
  const [cfg, setCfg] = useState('7')
  const [model, setModel] = useState('flux-dev')

  useEffect(() => {
    void loadImages(activeProjectId)
  }, [activeProjectId, loadImages])

  useEffect(() => {
    if (selectedImageId) {
      void loadImageVersions(selectedImageId)
    }
  }, [loadImageVersions, selectedImageId])

  const selectedImage = useMemo(
    () => images.find((image) => image.id === selectedImageId) ?? images[0],
    [images, selectedImageId],
  )

  const selectedVersions = selectedImage ? versions[selectedImage.id] ?? [] : []

  const styleList = useMemo(
    () => styles
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean),
    [styles],
  )

  const numericSeed = seed.trim() ? Number(seed) : undefined
  const numericSteps = steps.trim() ? Number(steps) : undefined
  const numericCfg = cfg.trim() ? Number(cfg) : undefined

  const generationPayload = {
    prompt,
    negativePrompt,
    styles: styleList,
    resolution,
    model,
    seed: Number.isFinite(numericSeed) ? numericSeed : undefined,
    steps: Number.isFinite(numericSteps) ? numericSteps : undefined,
    cfg: Number.isFinite(numericCfg) ? numericCfg : undefined,
  }

  const selectedProject = projects.find((project) => project.id === activeProjectId)

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
      <Panel title="Prompt Stack" subtitle="Templates, prompt versions, and generation controls">
        <div className="space-y-3">
          <label className="block text-xs uppercase tracking-widest text-slate-500">Prompt</label>
          <textarea
            className="min-h-24 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />

          <label className="block text-xs uppercase tracking-widest text-slate-500">Negative Prompt</label>
          <textarea
            className="min-h-16 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={negativePrompt}
            onChange={(event) => setNegativePrompt(event.target.value)}
          />

          <label className="block text-xs uppercase tracking-widest text-slate-500">Styles (comma separated)</label>
          <input
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={styles}
            onChange={(event) => setStyles(event.target.value)}
          />

          <div className="grid grid-cols-2 gap-2">
            <Input label="Resolution" value={resolution} onChange={setResolution} />
            <Input label="Model" value={model} onChange={setModel} />
            <Input label="Seed" value={seed} onChange={setSeed} />
            <Input label="Steps" value={steps} onChange={setSteps} />
            <Input label="CFG" value={cfg} onChange={setCfg} />
          </div>

          <div className="grid grid-cols-1 gap-2">
            <Button
              variant="accent"
              onClick={() => {
                void generateImage({ projectId: activeProjectId, ...generationPayload })
              }}
            >
              Generate
            </Button>
            <Button
              onClick={() => {
                if (!selectedImage) {
                  return
                }
                void createVariant(selectedImage.id, generationPayload)
              }}
            >
              Create Variant
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (!selectedImage) {
                  return
                }
                void regenerateImage(selectedImage.id, generationPayload)
              }}
            >
              Regenerate
            </Button>
          </div>
        </div>
      </Panel>

      <Panel title="Canvas + Version Timeline" subtitle="Current output, lineage, and review handoff">
        <div className="space-y-4">
          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-sm font-medium text-slate-100">Current Preview</h4>
              <span className="text-xs uppercase tracking-widest text-slate-500">{status}</span>
            </div>
            {selectedImage ? (
              <img
                src={selectedImage.uri}
                alt="Generated"
                className="h-[360px] w-full rounded border border-slate-700 object-cover"
              />
            ) : (
              <div className="flex h-[360px] items-center justify-center rounded border border-dashed border-slate-700 text-sm text-slate-500">
                No generated image yet
              </div>
            )}
            {error ? <p className="mt-2 text-xs text-rose-300">{error.message}</p> : null}
          </div>

          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-medium text-slate-100">Version Timeline</h4>
              <span className="text-xs text-slate-500">{selectedVersions.length} versions</span>
            </div>
            <ul className="space-y-2">
              {(selectedVersions.length > 0 ? selectedVersions : selectedImage ? [selectedImage] : []).map((image) => (
                <li key={image.id}>
                  <button
                    type="button"
                    className={`w-full rounded border px-3 py-2 text-left text-sm ${selectedImage?.id === image.id ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-100' : 'border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800'}`}
                    onClick={() => setSelectedImageId(image.id)}
                  >
                    <div className="flex items-center justify-between">
                      <span>Version {image.version}</span>
                      <span className="text-xs text-slate-500">{image.resolution ?? 'n/a'}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-slate-400">{image.prompt}</p>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Panel>

      <Panel title="Inspector + Review" subtitle="Metadata, lineage, execution trace, and approval handoff">
        <div className="space-y-2 text-sm text-slate-300">
          <InspectorRow label="Project" value={selectedProject?.name ?? activeProjectId} />
          <InspectorRow label="Image ID" value={selectedImage?.id ?? 'None'} />
          <InspectorRow label="Parent" value={selectedImage?.parent_asset_id ?? 'Root'} />
          <InspectorRow label="Version" value={selectedImage ? String(selectedImage.version) : 'n/a'} />
          <InspectorRow label="Provider" value={selectedImage?.provider ?? 'n/a'} />
          <InspectorRow label="Workflow" value={selectedImage?.workflow ?? 'image.generate'} />
          <InspectorRow label="Prompt Version" value={selectedImage ? String(selectedImage.prompt_version) : '0'} />
          <InspectorRow label="Seed" value={selectedImage?.seed != null ? String(selectedImage.seed) : 'auto'} />
          <InspectorRow label="Model" value={selectedImage?.model ?? model} />
          <Button
            onClick={() => {
              if (!selectedImage || !selectedProject) {
                return
              }
              void createReviewSession(selectedProject.id, `Image Review ${selectedImage.id}`, selectedImage.id)
            }}
          >
            Send To Review
          </Button>
        </div>
      </Panel>
    </section>
  )
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="space-y-1 text-xs uppercase tracking-widest text-slate-500">
      <span>{label}</span>
      <input
        className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm uppercase tracking-normal text-slate-100"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-900 px-3 py-2">
      <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 break-all text-slate-100">{value}</div>
    </div>
  )
}
