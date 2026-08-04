"""Website Factory (M015).

Builds, deploys and maintains real websites for real customers. Read ``M015.md``
and ``docs/WEBSITE_FACTORY.md`` before changing anything here.

Deliberately free of eager imports, matching ``media``, ``approval`` and
``opportunity``: import the submodule you need.

Three properties shape this package and are enforced rather than documented:
a build is reproducible from the durable record alone; Atlas owns the artifact
and the deployment state rather than the host; and nothing is promoted that
Atlas's own detector would flag on a stranger's site.
"""

__all__: list[str] = []
