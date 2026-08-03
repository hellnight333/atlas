"""Media domain (Milestone 013).

Two layers, deliberately separated:

* **Content** — ``Series``, ``Episode``, ``Script``, ``Scene``. What is being
  said. Knows nothing about video, resolution, codecs or providers.
* **Rendering** — ``Rendition``, ``SceneRender``. One rendered *form* of an
  episode. Everything medium-specific lives here.

The seam is the point. A short, a thumbnail set, a blog post, a podcast cut or a
translation is another ``Rendition`` of the same ``Script`` — not a migration.
The rule that keeps it honest: **a content table never gains a column that only
one output form needs.**

Milestone 013 builds exactly one rendition kind, ``video/1080p``. The tables
allow more; the product does not offer any yet.

Imports are not eager here, matching ``approval``: import the submodule you need.
"""

__all__: list[str] = []
