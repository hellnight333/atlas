# Atlas Studio Taxonomy

## 1. Purpose

This document defines the scalable taxonomy and navigation model for Studios.

It resolves shell scalability risk when Atlas grows to high studio counts, tool counts, and enterprise configurations.

This is the source of truth for Studio organization and discovery behavior.

## 2. Canonical Hierarchy

Required hierarchy:

- Capability
- Studio
- Workspace
- Tool
- Action

### 2.1 Definitions

Capability:

- strategic functional domain (for example: Research, Media, Build, Publish)

Studio:

- curated operating environment inside one capability

Workspace:

- context arrangement and active state within a studio

Tool:

- focused utility surface or operation interface inside workspace

Action:

- executable user intent on a tool or selected object

## 3. Taxonomy Rules

### 3.1 Capability Layer Constraints

- Capabilities are globally limited and stable.
- New capability creation requires architecture governance review.
- Capability names must be task-domain oriented, not team/department oriented.

### 3.2 Studio Layer Constraints

- Studios must map to exactly one primary capability.
- Cross-capability studios are represented as linked experiences, not duplicate studios.
- Studio purpose statement is mandatory and concise.

### 3.3 Workspace Layer Constraints

- Workspace templates are studio-scoped by default.
- Workspace portability across studios is opt-in and policy-gated.

### 3.4 Tool Layer Constraints

- Tools must declare capability fit and workspace role.
- Tool discoverability must not require deep navigation chains.

### 3.5 Action Layer Constraints

- Actions use global verb conventions.
- Action naming cannot diverge semantically across studios for same outcome.

## 4. Scale Targets

Target scaling envelope:

- 50+ Studios
- 500+ Tools
- thousands of Assets
- plugin and marketplace studio growth
- enterprise policy-driven studio visibility

## 5. Navigation Density Model

### 5.1 Maximum Visible Studios

At any time in primary shell navigation:

- **Pinned studios visible:** up to 8
- **Recent studios visible:** up to 6
- **Capability quick list visible:** all capabilities

All other studios are discoverable via Studio Directory and Quick Switcher.

Rationale:

Unlimited visible studio lists degrade scanability and orientation.

### 5.2 Grouping Model

Studio grouping priority:

1. Capability group
2. User pin group
3. Recent usage group
4. Enterprise-required group

### 5.3 Category Semantics

Studio categories:

- Core Studios
- Extended Studios
- Marketplace Studios
- Plugin Studios
- Enterprise Managed Studios

## 6. Discovery Model

### 6.1 Studio Directory

Directory provides:

- capability browsing
- filter by role, task type, verification level
- install/enable status
- usage and recommendation signals

### 6.2 Quick Switcher

Quick Switcher responsibilities:

- rapid context jump between studios and workspaces
- ranked by recency, intent, and project relevance

Quick Switcher does not execute tool actions.

### 6.3 Search Integration

Universal Search can locate studios and studio assets, but does not replace taxonomy governance.

## 7. Favorites, Pins, and Recents

### 7.1 Favorites

- durable cross-project preference
- low churn list

### 7.2 Pins

- project- or workspace-specific active focus
- higher churn than favorites

### 7.3 Recents

- automatically generated interaction history
- decays by recency and relevance

## 8. Enterprise Scaling

Enterprise controls:

- role-based studio visibility
- policy-locked studios
- organization-required studio bundles
- tenant-specific studio naming overlays

Enterprise policy cannot break canonical capability mapping.

## 9. Plugin and Marketplace Studios

### 9.1 Plugin Studios

- must declare capability and compatibility matrix
- default to limited visibility until trust conditions met

### 9.2 Marketplace Studios

- discoverable through directory and marketplace channels
- clear verification and maintenance metadata required

### 9.3 Containment

External studios cannot rewrite core taxonomy behavior.

## 10. Anti-Ambiguity Rules

1. Studio is not a synonym for Tool.
2. Capability naming cannot mirror implementation architecture.
3. No duplicate studios with overlapping purpose in same capability without explicit differentiation.
4. Sidebar should not become the full studio registry.
5. Discovery and execution channels must remain distinct.

## 11. Cross-References

- Shell integration: DESKTOP_SHELL_V1.md
- Command boundary: COMMAND_SYSTEM.md
- Search interactions: UNIVERSAL_SEARCH.md
- Plugin trust and lifecycle: PLUGIN_GOVERNANCE.md
- Enterprise visibility controls: ENTERPRISE_SHELL.md