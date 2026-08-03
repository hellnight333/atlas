# Installing Atlas

Atlas bundles its own PostgreSQL database and its own Python runtime. You do
not need to install either, and Atlas will not touch a database you already
have.

Download from [Releases](https://github.com/hellnight333/atlas/releases).

| Platform | Files |
|---|---|
| Windows | `Atlas_<version>_x64-setup.exe`, `..._portable.zip` |
| macOS (Apple Silicon) | `Atlas_<version>_aarch64.dmg`, `..._aarch64.app.zip` |
| macOS (Intel) | `Atlas_<version>_x86_64.dmg`, `..._x86_64.app.zip` |
| Linux | `Atlas_<version>.AppImage`, `..._linux-x86_64.tar.gz` |

Roughly 140 MB compressed, 300 MB installed. Most of that is PostgreSQL.

## Verify your download first

**Alpha builds are unsigned**, so your operating system cannot vouch for them.
Checking the SHA-256 is how you confirm the file is the one that was published.
`SHA256SUMS.txt` is attached to every release.

```bash
shasum -a 256 Atlas_0.12.0-alpha.1_aarch64.dmg      # macOS / Linux
certutil -hashfile Atlas_0.12.0-alpha.1_x64-setup.exe SHA256   # Windows
```

Compare it to the line in `SHA256SUMS.txt`. If they differ, do not run it.

## macOS

Open the `.dmg` and drag Atlas to Applications.

On first launch macOS will say **"Atlas cannot be opened because the developer
cannot be verified."** This is expected: the build is not signed with an Apple
Developer ID, which costs 99 USD a year and is not part of the alpha.

To open it anyway:

1. **Right-click** Atlas in Applications and choose **Open**.
2. Click **Open** in the dialog.

Right-click → Open is the specific gesture macOS accepts as consent.
Double-clicking will keep refusing. You only do this once.

If macOS says the app is *damaged*, it was quarantined during download:

```bash
xattr -dr com.apple.quarantine /Applications/Atlas.app
```

Minimum: macOS 10.15. Apple Silicon and Intel have separate downloads — the
wrong one will not run.

## Windows

Run the `-setup.exe`.

SmartScreen will show **"Windows protected your PC"** because the build is not
code-signed. Click **More info**, then **Run anyway**.

The installer places Atlas in Program Files and adds a Start menu entry.

Prefer no installer? Use `..._portable.zip`: unzip it and run `Atlas.exe` from
the folder. Everything stays inside that folder, so it works from a USB drive.

## Linux

**AppImage:**

```bash
chmod +x Atlas_0.12.0-alpha.1.AppImage
./Atlas_0.12.0-alpha.1.AppImage
```

Needs FUSE. On Ubuntu: `sudo apt install libfuse2`.

**Tarball:**

```bash
tar -xzf Atlas_0.12.0-alpha.1_linux-x86_64.tar.gz
cd Atlas && ./atlas
```

Built on Ubuntu 22.04, so it runs on 22.04 and newer. Older distributions with
an older glibc are not supported.

## Where Atlas keeps your data

| Platform | Location |
|---|---|
| macOS | `~/Library/Application Support/io.github.hellnight333.atlas` |
| Windows | `%APPDATA%\io.github.hellnight333.atlas` |
| Linux | `~/.local/share/io.github.hellnight333.atlas` |

This folder holds the PostgreSQL cluster and everything you create. Back it up
and you have backed up Atlas.

To keep data beside the application instead — a portable install — set
`ATLAS_DATA_DIR` to a folder of your choosing.

## Uninstalling

1. Remove the application: drag to Trash (macOS), Add or Remove Programs
   (Windows), delete the AppImage or folder (Linux).
2. Delete the data folder above.

That is a complete removal. Atlas has no account, no cloud state and no
registry keys beyond what the Windows installer creates. Nothing survives
elsewhere.

## First launch

The first launch is slower — Atlas is creating a database cluster. The window
names each stage.

If it fails, the screen shows the reason and offers the database log. The most
common cause is a data folder Atlas cannot write to.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md), then
[QUICK_START.md](QUICK_START.md).

## Building from source

See [PACKAGING.md](PACKAGING.md). You need Rust, Node 22 and Python 3.13.
