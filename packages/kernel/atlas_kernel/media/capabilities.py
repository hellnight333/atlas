"""What can be asked for, independent of who can do it.

Capabilities are the only vocabulary the kernel uses to describe work. Workers
satisfy capabilities; the scheduler picks workers; nothing above that layer
knows whether a frame came from Wan, ComfyUI, Veo, Seedance, LTX or something
that does not exist yet.

Naming them in one module rather than as string literals scattered through
services is the difference between a taxonomy and a habit. A typo here is an
import error; a typo in a literal is a provider that silently never matches.
"""

from __future__ import annotations

from typing import Final

#: Moving pictures from a prompt.
VIDEO_GENERATE: Final = "video.generate"
#: Still images from a prompt -- thumbnails, cards, stills.
IMAGE_GENERATE: Final = "image.generate"
#: Spoken word from text. Narration, dialogue, a podcast host.
SPEECH_GENERATE: Final = "speech.generate"
#: Music, whether composed or selected from a licensed library.
MUSIC_GENERATE: Final = "music.generate"
#: Timed text. The MVP derives cues from the script it already has, which is
#: more accurate than transcribing speech back into text -- this capability is
#: for the cases the script cannot serve, such as translation or transcribing
#: media Atlas did not author.
SUBTITLE_GENERATE: Final = "subtitle.generate"
#: Long-form prose. Blog posts, newsletters, listings.
TEXT_GENERATE: Final = "text.generate"

ALL: Final = (
    VIDEO_GENERATE,
    IMAGE_GENERATE,
    SPEECH_GENERATE,
    MUSIC_GENERATE,
    SUBTITLE_GENERATE,
    TEXT_GENERATE,
)
