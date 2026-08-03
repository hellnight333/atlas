# Release checklist

Cutting a release is one tag push. This is what to verify before pushing it,
and what to check afterwards.

## Before tagging

- [ ] `CHANGELOG.md` has a `## [<version>]` section — the release notes are
      extracted from it, so a missing section means an empty release body
- [ ] `atlas_kernel/version.py` `VERSION` matches the tag (without the `v`)
- [ ] `apps/desktop/package.json`, `tauri.conf.json` and `Cargo.toml` agree —
      `test_desktop_and_kernel_versions_agree` enforces this
- [ ] `docs/KNOWN_ISSUES.md` reflects reality for this build
- [ ] `docs/IMPLEMENTATION_STATUS.md` still matches the code
- [ ] All gates green: `ruff`, `black`, `mypy`, `pytest` (90% floor),
      `tsc`, `npm run build`, `npm run lint`, `cargo fmt`, `cargo clippy`

## Tag and push

```bash
git tag -a v0.12.0-alpha.1 -m "Atlas Public Alpha"
git push origin v0.12.0-alpha.1
```

`release.yml` then builds on four native runners — Tauri cannot cross-compile —
and publishes the release.

## After the workflow finishes

- [ ] Six installer artifacts plus `SHA256SUMS.txt` are attached
- [ ] The release is marked **pre-release** (automatic for alpha/beta/rc tags)
- [ ] Release notes rendered from the changelog section
- [ ] Download one artifact and verify its checksum against the published file
- [ ] Install it on a clean machine: first run completes, a demo installs, and
      an enabled rule applies

## Rollback

Releases are not deleted — a published artifact may already be running
somewhere. Mark the release as a draft, publish a corrected version, and note
the problem in `KNOWN_ISSUES.md`.

## Not automated, deliberately

- **Signing.** No certificate is invented. See
  [PACKAGING.md](PACKAGING.md) for exactly which secrets to add when one exists.
- **Announcements.** Written by a person, after the artifacts are verified.
