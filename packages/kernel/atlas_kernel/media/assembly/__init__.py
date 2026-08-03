"""Assembling scenes into a finished rendition.

Nothing in ``base`` knows what a codec is. An assembler receives an ordered set
of scenes with whatever was rendered for each, and returns a finished artefact
-- and that description is true of a video, a podcast episode, a thumbnail set,
a blog post, a listing or a landing page.

``video`` is the first and, for M013, the only implementation. A second one
registers itself for its own ``RenditionKind`` and every caller stays unchanged,
because callers resolve an assembler by kind and never branch on it.

Imports are not eager. Import the submodule you need.
"""

__all__: list[str] = []
