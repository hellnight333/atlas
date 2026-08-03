"""Publisher implementations.

The abstraction lives in ``media.publishing``: a publisher takes a finished file
and some metadata and returns a receipt. YouTube is the first implementation and
the only one M013 builds.

Facebook, Instagram, TikTok, LinkedIn, a website, a podcast feed, a newsletter
or a marketplace listing each become another module here. None of them require a
change to the gate, the workflow, or anything upstream -- which is the entire
reason the protocol is three lines long.

Imports are not eager: the YouTube publisher reaches for network libraries that
a caller publishing nowhere should not have to load.
"""

__all__: list[str] = []
