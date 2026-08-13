# Qevik — Architecture

## Generic assembly
Generic assembly/timeline code should not contain video-specific concepts such as frames, codecs, resolutions or ffmpeg. Video is one implementation.

## Generic timing
Timing belongs in the generic timeline layer. Video may have subtitles; podcasts may have chapters.

## Capability vocabulary
Central vocabulary discussed:
- `video.generate`
- `image.generate`
- `speech.generate`
- `music.generate`
- `subtitle.generate`
- `text.generate`

`audio.narrate` was normalized to `speech.generate`.

## Subtitles
Prefer deriving subtitles from the known script. `subtitle.generate` is for translation or media whose text is not already known.

## Provider abstraction
A universal provider wrapper was rejected. Keep capability interfaces narrow and provider adapters separate. Design against at least two providers before stabilizing an abstraction.

## Connections
Every connection has explicit ownership:
- Qevik/Atlas
- or a specific Business

Never ambiguous. A business-owned mailbox is never Qevik's outreach channel.

## Secrets
Secret values should not stringify; explicit reveal should be required. The connection table intentionally has no arbitrary token column.

## Refresh
OAuth refresh is single-flight to prevent rotating refresh-token races.

## External identity
Use `ExternalIdentity`, not `ProviderAccount`, because "account" has customer-domain meaning.

## First slice
One real provider + one capability should be verified before building a complete integration platform.
