# The GPU worker

Everything Atlas needs in order to render on a real GPU. M013 is complete except
for this: the whole pipeline runs end to end against mocks, and the milestone is
explicitly not finished while `mock-video` is in the path.

This document exists so that connecting takes an afternoon rather than a week of
rediscovery. Read [The placement decision](#the-placement-decision) first — it is
the one thing that is easy to get wrong and expensive to undo.

---

## The placement decision

**The ComfyUI adapter runs on the worker, not on the kernel.**

This is not obvious, and getting it wrong produces something that works on a
desk and cannot be deployed.

`LongRunningProvider` (`media/providers/base.py`) is *called by* whoever holds
it — `submit`, `poll`, `fetch`. If the kernel held a ComfyUI adapter, the kernel
would call ComfyUI's HTTP API, which means **an inbound connection to the GPU
box**. `CLAUDE.md` is explicit that workers long-poll outbound over Tailscale and
never open an inbound port, and that is the right call: a GPU box that accepts
inbound connections is a GPU box you have to firewall, certificate and monitor.

So the flow inverts:

```
kernel host                          GPU worker (no inbound ports)
───────────                          ─────────────────────────────
QueueProvider.submit()               Worker.poll_once()      ── outbound ──►
  → enqueues a job                     → leases the job
QueueProvider.poll()                   → ComfyUIAdapter.submit()   (localhost)
  → reads job status                   → polls ComfyUI            (localhost)
QueueProvider.fetch()                  → downloads the frames     (localhost)
  → reads the produced asset           → writes the asset
```

The three-method protocol fits both sides unchanged, which is the useful part:
`submit`/`poll`/`fetch` describe a queued job exactly as well as they describe a
remote render. Two adapters are needed, and neither is large:

| Adapter | Runs on | `submit` | `poll` | `fetch` |
|---|---|---|---|---|
| `QueueProvider` | kernel | enqueue a job, return its id | read job status | read the produced asset |
| `ComfyUIAdapter` | worker | `POST /prompt` | `GET /history/{id}` | `GET /view` |

Everything else in the Media Factory is unchanged by this. The render service
asks the registry for `video.generate` and never learns which of the two
answered — which is the whole reason it was built that way.

---

## Host

Per `CLAUDE.md`, both GPU nodes run an identical image. One OS, one playbook,
one set of bugs.

| | |
|---|---|
| OS | Ubuntu 24.04 LTS Server |
| Driver | NVIDIA proprietary, **on the host only** |
| CUDA | **Inside containers**, so workloads pin their own version |
| Secure Boot | **OFF in BIOS** |
| Provisioning | `infra/provision_node.sh` — two stages, reboot between |

**Secure Boot must be off before you start.** With it on, the proprietary driver
needs MOK signing on every update, which turns each driver bump into a physical
visit to the machine.

### VRAM

The pinned recipe is Wan 2.1 T2V **1.3B**, chosen over 14B because it fits a
single consumer card and the difference is not visible at 720p and five seconds.

Approximately 8–10 GB at 720p / 81 frames. Approximately, because **this has not
been measured on the target card** — nothing has. Treat it as a starting point
and record the real figure in the recipe's benchmark fields once it is known.

---

## ComfyUI

Headless, as a service. The GUI is never the source of truth.

```bash
python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch
```

Bound to **loopback**. The adapter runs on the same machine, so ComfyUI has no
reason to be reachable from anywhere else — and every reason not to be.

Three endpoints are used, and no others:

| Endpoint | Purpose |
|---|---|
| `POST /prompt` | queue a graph; returns `prompt_id` |
| `GET /history/{prompt_id}` | completion and output filenames |
| `GET /view?filename=&subfolder=&type=output` | download the result |

### Models

The ComfyUI-native Wan layout:

```
models/diffusion_models/   wan2.1_t2v_1.3B_*.safetensors
models/text_encoders/      umt5_xxl_*.safetensors
models/vae/                wan_2.1_vae.safetensors
```

**Confirm the exact filenames against what you actually install**, and put those
names in the recipe rather than these. The recipe pins the checkpoint by name
and provenance records it, so a name that is nearly right produces renders that
cannot be reproduced.

HuggingFace licence acceptance is required before the weights will download, and
it is an interactive click. Atlas cannot do it.

---

## Network

Tailscale, outbound only. The worker reaches Postgres on the Hetzner control
plane; nothing reaches the worker.

- Tailscale account authorisation is interactive — Atlas cannot do it.
- The worker needs `ATLAS_DATABASE_URL` pointing at the control-plane Postgres
  over the tailnet.
- NAS / MinIO credentials, if assets are to live there rather than on local disk.

---

## Pinning the workflow

`recipes/video/wan-t2v-720p.yaml` is written and pinned — seed, sampler, steps,
cfg, negative prompt — **except its graph**, which is deliberately absent:

```yaml
# workflow: ../workflows/wan_t2v_720p.json
```

The loader hashes the graph and provenance records that hash, so committing an
unverified file would claim a reproducibility the recipe does not have. When the
worker exists:

1. Build the graph in ComfyUI and **run it** until it produces something good.
2. Export **API format** (not the UI save — they are different files).
3. Commit it to `recipes/workflows/wan_t2v_720p.json`.
4. Uncomment the `workflow:` line.
5. Fill in `estimated_seconds_per_second` from a real render, replacing the
   current placeholder of 14. That number is what an operator is shown before
   approving a re-render, and a wrong one is worse than none.

The recipe loader will refuse to start if the file is missing, so step 4 cannot
be done prematurely by accident.

---

## Bringing it up, in order

Each step is verifiable on its own. Do not skip ahead: a failure three steps
later is much harder to attribute.

1. **Driver.** `nvidia-smi` lists the card.
2. **Tailscale.** The worker can reach the control-plane Postgres.
3. **ComfyUI.** `curl localhost:8188/system_stats` answers.
4. **A graph, by hand.** Produce one clip in the ComfyUI UI. Nothing about Atlas
   is involved yet, and if this does not work nothing downstream can.
5. **Export and commit the API graph**, then uncomment `workflow:`.
6. **`ComfyUIAdapter`** — the three calls above. Point it at localhost and
   render one scene from a recipe.
7. **`QueueProvider`** on the kernel, registered for `video.generate` with
   `is_local=True`. The router prefers it over anything cloud automatically.
8. **Remove `mock-video` from the registration.**

## M013 is complete when all three are true

Not before. Each is a thing that has happened, not a thing that is built.

- [ ] **The mock provider is gone.** `mock-video` is no longer registered for
      `video.generate`; the real ComfyUI/Wan provider serves it.
- [ ] **One complete end-to-end render.** A brief becomes scenes, scenes render
      on the GPU, and the assembled MP4 exists in the Library with provenance
      that `is_reproducible()` reports as complete.
- [ ] **One real private YouTube upload.** Approved by a person, uploaded, and
      visible on the test channel as private.

Everything upstream of these is already done and tested. `mock-tts` and
`mock-music` may remain — narration and music are not what M013 set out to
prove, and replacing them is a later milestone's work.

---

## Known gaps to fix when this is real

Both are fine for one worker and wrong for several. Neither is worth fixing
before there is a machine to test against.

- **`Worker.poll_once` has no `SKIP LOCKED`.** It scans for the first queued job
  and marks it running. Two workers will race and both take the same job.
  `CLAUDE.md` specifies `SKIP LOCKED`; the code does not implement it yet.
- **No lease expiry on the render path.** A worker killed mid-render leaves the
  job `RUNNING` forever. The cluster module has reservations and leases; the
  media render path does not use them.

---

## What Atlas already does, so you do not have to build it

Worth knowing before writing anything: these are done, tested, and waiting.

- **Capability routing**, local-first. Register `QueueProvider` with
  `is_local=True` and it wins over cloud without any policy change.
- **Provenance.** Every render records provider, model, recipe, workflow hash,
  seed, LoRAs and resolved parameters. `is_reproducible()` reports honestly what
  is missing rather than implying a guarantee.
- **Partial regeneration.** A dependency graph decides what to rebuild. Rewriting
  narration re-voices one scene and leaves its picture untouched — proved by a
  test that counts provider calls, not bytes.
- **Assembly.** Scenes, narration, captions, music and transitions into one MP4.
- **One approval, on the outcome**, then the whole plan executes unattended.
- **Publishing.** YouTube, private-only, refusing public rather than clamping it.

The GPU is the last piece, not the first.
