# Atlas Domain Glossary

## Capability
A stable semantic intent requested by a workflow node, independent of provider, model, or execution location.

## Recipe
A named implementation profile for a capability, describing pipeline parameters and metadata without execution logic.

## Requirement
Constraints attached to a workflow node or request, such as minimum VRAM, offline-only mode, cost ceiling, or latency target.

## Execution Policy
The decision layer that selects a recipe, executor kind, and provider implementation for a capability request.

## Capability Registry
The domain registry that stores capabilities, capability metadata/version, recipes, and compatibility views.

## Action
An executable kernel operation exposed through the action registry and used by jobs and workflow nodes.

## Workflow
A reusable orchestration template describing nodes and dependency edges.

## Run
A concrete execution instance of a workflow.

## Job
A schedulable unit created by orchestration and executed through executor/provider abstractions.

## Executor
The location abstraction for execution (local, docker, remote, cluster, cloud, or runtime-specific kinds).

## Provider
An implementation adapter that fulfills actions/capabilities through a concrete runtime or service.

## Asset
A first-class produced artifact with lineage, metadata, and run/job association.
