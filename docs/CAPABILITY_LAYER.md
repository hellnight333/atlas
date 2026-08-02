# Atlas Capability Layer

## Objective

The Capability Layer provides a semantic abstraction between workflows and execution implementations.

Workflows describe intent.
Capabilities describe meaning.
Recipes describe implementation variants.
Selection policy chooses implementation.

## Design

Capability layer responsibilities:

- Register capabilities and versions.
- Register recipes per capability.
- Provide capability and recipe discovery APIs.
- Expose compatible provider lookup.
- Expose compatible executor lookup.

Capability layer non-responsibilities:

- No job execution.
- No provider invocation.
- No model logic.
- No executor routing logic.

## Semantic Flow

Workflow -> Capability -> Recipe -> Execution Policy -> Executor -> Provider -> Model

## Core Objects

- Capability: stable, provider-agnostic intention.
- Recipe: implementation profile for a capability.
- Requirement: node constraints such as VRAM, latency, or cost targets.
- Compatibility metadata: provider kinds and executor kinds supported by a capability.

## API Surface

Additive endpoints:

- GET /capabilities
- GET /capabilities/{id}
- GET /capabilities/{id}/recipes
- GET /capabilities/{id}/providers
- GET /capabilities/{id}/executors
- POST /capabilities
- POST /recipes

Optional event endpoint:

- POST /capabilities/{id}/recipes/{recipe_id}/select

## Events

Capability layer events are typed and optional for subscribers:

- CapabilityRegistered
- CapabilityUpdated
- RecipeRegistered
- RecipeSelected

## Rules

- Workflows never reference providers directly.
- Workflows never reference models directly.
- Recipes define parameters and metadata, not execution logic.
- Selection policy remains external to capability objects.
- Executors and providers remain replaceable.

## Extensibility

The design supports future additions without breaking existing contracts:

- plugin capability registration
- capability versioning strategies
- capability benchmarking
- capability marketplace and discovery
- recommendation services
