"""Media providers.

``base`` defines the only abstraction M013 adds: a three-method protocol for
work that outlives a request. ``mock`` is the stand-in until a GPU exists, and
it produces real media rather than a placeholder URI -- see the module docstring
for why that distinction is the difference between a useful mock and a lie.

Imports are not eager. Import the submodule you need.
"""

__all__: list[str] = []
