# Plugin SDK — interface freeze

**Status: interfaces only. There is no plugin loader, and no plugin can be
installed today.**

Stated first because the alternative is someone spending an evening writing a
plugin that nothing can load. `/health/report` reports plugins as healthy with
`sdk_available: false` — that is honest, not a fault.

## What is frozen

The extension *shapes* below are frozen for `0.12.x`, so anything designed
against them will still fit when a loader arrives.

### Provider contract

```python
class ProviderAdapter(ABC):
    @abstractmethod
    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...
```

One method. `action` is a capability verb (`image.generate`, `text.generate`);
`payload` is its arguments. Registration happens in the composition root, which
is the only place objects are constructed.

Deliberately minimal: the kernel handles scheduling, placement, approval,
retries, lineage and recovery. An adapter's whole job is to call one thing and
return a dictionary.

### Capability declaration

A capability declares an id, name, description, version, supported provider
kinds and supported executor kinds. Three ship today: image generation,
reasoning, and text generation.

### Tool and action registration

Automation actions are registered in `ACTION_CATALOG` as either `EXECUTABLE`
(routes to a provider) or `STATE` (coordinates Atlas itself and never touches a
provider). That split is frozen — it is what lets automation run with no
credentials.

### Studio registration

**Placeholder.** `/studios` returns fixed sample data rather than a registry.
The shape is not frozen and will change.

## What is missing before a plugin can exist

- A loader — discovery, load order, failure isolation
- A manifest format
- A permission model, so a plugin cannot quietly reach the database
- Versioning and compatibility checks
- Signing or a trust decision

Each is a real design question, and shipping a loader without them would be
worse than shipping none.

## No marketplace

Not planned. A marketplace is a curation and trust burden that does not serve
the core product.

## If you want to build one anyway

Write against `ProviderAdapter` and register it in the composition root — as a
fork, not a plugin. Open an issue first: the recipe design lands before the
loader, and an adapter written now will likely need reshaping around it.
