# Video Factory — M013 architecture

> **Milestone outcome, and the only definition of done:**
> Atlas takes a brief, produces a **scene-based** video with narration, subtitles
> and music, holds it for a **human approval**, and then **uploads it to a
> private YouTube test channel** — and reports the upload back.
>
> Not "the pipeline is built". Not "the adapters exist". One real video, on a
> real channel, approved by a person.

This document is the plan for that. It is deliberately narrow. Everything that
does not serve the first working video is named in [Out of scope](#out-of-scope)
and deferred.

---

## The shape

```
CONTENT  (medium-agnostic — knows nothing about video)

  brief → Series → Episode → Script → Scene, Scene, Scene…
                                         each: heading, narration text,
                                               visual direction, duration

─────────────────────────────────────────────────────────────────────
RENDERING  (medium-specific — one Rendition per output form)

  Rendition (kind: video/1080p)
      │
      ├─ SceneRender per Scene   one job each, independent, retryable
      │                          ◄── partial regeneration happens here
      ├─ narration per Scene     TTS
      │
      ▼
  assemble   ffmpeg: renders + narration + subtitles + music + transitions
      │
      ▼
  APPROVAL GATE   a person watches it and approves. Nothing proceeds without this.
      │
      ▼
  Publication     YouTube upload, privacy forced to private/unlisted
```

M013 builds **exactly one** Rendition kind and **one** publish target. The line
across the middle is the only concession to the future, and it is a seam rather
than a feature.

---

## Content is separate from rendering

The single most consequential decision here, and the one most expensive to
retrofit.

**A Script and its Scenes describe *content*. They contain no video concepts at
all** — no resolution, no codec, no frame count, no provider, no asset. A Scene
is a narrative beat: a heading, the words to be spoken, the visual direction,
and roughly how long it should run.

Everything video-specific lives one layer down, in a **Rendition**. A Rendition
is one rendered form of an Episode. M013 builds a single kind, `video/1080p`.
Later, a short, a thumbnail set, a blog post, a podcast cut or a translation is
*another Rendition of the same Script* — no migration, no reshaping, no
rewriting the pipeline that already works.

The test for whether the seam is in the right place: **a blog post renderer must
never need a column that a video renderer added.** If content and rendering were
one table, the first non-video output would force a migration across everything.

This is a data-model decision only. It adds no MVP scope: M013 still builds one
Rendition kind, one publish target, one path.

### Content layer — medium-agnostic

| Entity | Holds | Notes |
|---|---|---|
| `Series` | name, description, default channel | a long-lived body of related episodes. M013 creates one implicitly; no UI |
| `Episode` | series, brief, title, status | one unit of content |
| `Script` | episode, version, model + recipe that wrote it | versioned, so a rewrite does not destroy the old one |
| `Scene` | script, index, heading, narration text, visual direction, target seconds | **the narrative beat.** No media fields, ever |

`Script` is versioned because rewriting the script is a normal thing to want,
and because a Rendition must be able to say which script version it was built
from.

**On the name `Series`.** Not `Campaign`: Atlas is meant to run media properties
for years, and a campaign is by definition something that ends. Not `Studio`:
that word is already Atlas's own — a studio is one of the six capability
plugins, and reusing it would collide with the architecture's most load-bearing
noun. Not `Channel`: a series *has* a channel and may eventually publish the
same episode to several, so the two are not the same thing. `Series`/`Episode`
is also the pairing every reader already knows. If a brand ever needs to own
several series, `Brand` becomes a parent — additive, unlike a rename.

### Rendering layer — medium-specific

| Entity | Holds | Notes |
|---|---|---|
| `Rendition` | episode, script version, kind (`video/1080p`), scene_hash, final asset, status | one rendered output form |
| `SceneRender` | rendition, scene, provider, recipe, media asset, audio asset, status | **the unit of rendering work** |

A `Scene` is the unit of *authoring*. A `SceneRender` is the unit of *work* —
one render job, retryable on its own. Partial regeneration re-runs one
`SceneRender`, leaving its `Scene` and every sibling untouched: no GPU time, no
cost, no waiting. One scene failing is one scene failing, not a dead video.

`Rendition.scene_hash` fingerprints the `SceneRender` outputs the cut was built
from. If it no longer matches, the cut is stale and says so, rather than
silently shipping a video that does not match its scenes.

### Publishing layer

| Entity | Holds | Notes |
|---|---|---|
| `Publication` | rendition, approval id, platform, remote id, privacy, status | one row per upload attempt |

Separate from `Rendition` because uploads get retried, and because the approval
that authorised a specific upload must stay auditable afterwards.

### What M013 actually creates

One `Series` (implicit), one `Episode`, one `Script` at version 1, three to
five `Scene`s, one `Rendition`, one `SceneRender` per scene, one `Publication`.
No series management, no episode browser, no rendition picker. The tables
exist; the product surface does not.

---

## Provider abstraction: the minimum, and no more

The existing `ProviderAdapter.execute(action, payload) -> dict` is **synchronous
and blocking**. That is fine for the two simulation stubs. It is wrong for video:
a Wan render is minutes of work on a remote GPU, and blocking a worker thread on
it is not a design, it is a mistake waiting to be found in production.

So exactly one new protocol, with exactly three methods:

```python
class LongRunningProvider(Protocol):
    """A provider whose work outlives a request.

    Three methods because a remote job genuinely has three moments: you start
    it, you ask how it is going, and you collect it. Not a general async
    framework -- the smallest thing that lets a GPU render for four minutes
    without a thread parked on it.
    """

    def submit(self, recipe: RecipeSpec, params: dict) -> str: ...      # → handle
    def poll(self, handle: str) -> ProviderJobStatus: ...               # → state + progress
    def fetch(self, handle: str) -> bytes: ...                          # → the artefact
```

**That is the whole abstraction.** No capability negotiation protocol, no
streaming interface, no provider lifecycle hooks, no plugin discovery. Those are
speculative until a second real provider exists and disagrees with the first.

`ProviderAdapter` is left alone. The stubs keep working. This is additive.

### Local-first is already there

`ProviderRouter.select_provider` sorts by `(not is_local, cost_per_unit,
p50_latency_ms)` — local providers already win. It does not need rewriting; it
needs real providers registered with honest `ProviderSpec` values.

Cloud is therefore not a branch in the architecture. It is a provider with
`is_local=False` that the router reaches for only when no local provider can
serve the capability. If no local provider is registered and cloud is disabled,
the job fails with a clear reason — which is the correct behaviour for a
local-first system, not a bug.

### What we build first

| Provider | Kind | Status in M013 |
|---|---|---|
| `comfy-wan-t2v` | local video | **the real one** — ComfyUI `/prompt` → `/history` → download |
| `mock-video` | local video | stands in until the GPU exists (see below) |
| `mock-tts` → `local-kokoro` | local audio | narration |
| cloud video | fallback | **only if** local proves impossible; not built speculatively |

---

## Mocks that produce real media

The GPU worker and the YouTube credentials arrive later, so parts of this must
be mocked now. The question is *where the seam goes*, and the answer decides
whether the mock is useful or a lie.

**The seam is at the provider boundary, and the mock returns a genuine playable
file.** `mock-video` renders a real MP4 with ffmpeg — solid colour field, the
scene index and prompt burned in, correct duration and resolution. `mock-tts`
produces real audio of the right length.

Everything downstream is then production code running on production data:
assembly genuinely muxes real streams, subtitles genuinely burn in, the approval
gate genuinely holds a real file, and the YouTube uploader genuinely uploads
watchable video. When the Z8 appears, one provider is swapped and nothing else
changes.

A mock that returned `{"uri": "https://example.com/..."}` would prove nothing —
that is precisely the trap the current `local-flux` stub fell into, and why
Atlas today has a complete orchestration layer that has never moved a byte.

**The milestone is not complete while `mock-video` is in the path.** It is
scaffolding to keep the other 90% honest, not a deliverable.

---

## Recipes

`recipes/video/*.yaml`, versioned in git, one per generation profile:

```yaml
id: wan-t2v-720p-5s
version: 1.0.0
capability: video.generate
provider: comfy-wan-t2v
graph: graphs/wan_t2v_720p.json     # the ComfyUI API graph, pinned
parameters:
  width: 1280
  height: 720
  frames: 81
  fps: 16
  steps: 30
  sampler: uni_pc
  checkpoint: wan2.1-t2v-1.3b.safetensors
```

The LLM picks a recipe **by name**. It never authors or edits a node graph —
that rule is not negotiable and is why the graph is a pinned file rather than a
generated payload.

---

## Approval, and the publish guard

Reuses `ApprovalService` unchanged: `create_request` before publishing, and the
upload runs only on `approve`. Rejection stops it; the audit trail already
exists.

Two guards on top, because publishing is the irreversible step:

1. **Privacy is forced.** The uploader sets `privacyStatus` to `private` or
   `unlisted` and **refuses to run at all if asked for `public`** — a hard error,
   not a default that can be overridden by a config typo.
2. **Approval is verified at upload time,** not assumed from control flow. The
   uploader re-reads the approval by id and checks it is approved and unexpired
   before opening the connection.

---

## Order of work

Each step ends somewhere demonstrable, so progress is visible rather than
asserted.

1. **Data model + repository.** Migration and CRUD for the content layer
   (`Series`/`Episode`/`Script`/`Scene`) and the rendering layer
   (`Rendition`/`SceneRender`), with the seam enforced: no media column on a
   content table.
2. **`mock-video` + `mock-tts` producing real files.** Proves the seam.
3. **Scene render jobs through the kernel.** One job per `SceneRender`, real
   assets, lineage. *Demo: five scene files land in the Library.*
4. **Assembly.** ffmpeg concat, narration mux, burned subtitles, music bed,
   crossfades. *Demo: one watchable MP4.*
5. **Partial regeneration.** Re-render one `SceneRender`, reassemble, stale-hash
   handling. *Demo: scene 3 changes, others untouched.*
6. **Approval gate.** Publish blocked until a person approves.
7. **YouTube publisher.** OAuth, metadata, thumbnail, upload, status verify.
   *Demo: a private video on the test channel.*
8. **Swap in the real ComfyUI provider** when the GPU lands. *Milestone done.*

Steps 1–7 need no hardware and no credentials beyond the last one. Step 8 is the
only one gated on the Z8.

---

## Out of scope

Named so they stay out until one video exists end to end:

- **Any second Rendition kind.** Shorts, thumbnails, blog posts, podcasts,
  translations and social posts are what the content/rendering seam exists *for*
  — they are not built here. The tables make them cheap later; nothing more.
- Series or episode management surfaces — no browser, no scheduling, no
  cadence enforcement.
- Multi-provider routing policy, benchmark harness, quality scoring.
- Cloud video adapters — unless local generation proves impossible.
- More than 5 scenes; b-roll; stock footage; image-to-video.
- Voice cloning, multi-speaker narration, music generation (a licensed bed
  track is enough).
- Scheduling beyond "upload now"; multi-platform publishing; TikTok.
- A rich Video Studio UI. One page: brief in, scenes with per-scene regenerate,
  preview, approve, publish.
- Retry/backoff sophistication beyond "a failed scene can be re-run".

---

## Known risks

- **The GPU is the critical path.** Steps 1–7 are built against mocks; if the Z8
  slips, the milestone cannot complete, only be *ready* to complete. Flagged now
  rather than at the end.
- **ComfyUI graph drift.** Pinning the graph JSON in git is the mitigation; a
  graph edited in the GUI is not the source of truth.
- **YouTube quota.** Uploads cost ~1600 quota units against a default 10,000/day.
  Fine for a test channel, worth knowing before a retry loop is written.
- **Wan VRAM.** 1.3B fits comfortably; 14B does not fit every card. The recipe
  pins the checkpoint so this is a recipe choice, not a runtime surprise.
