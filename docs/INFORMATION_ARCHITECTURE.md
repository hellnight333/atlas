# Atlas Information Architecture

## 1. IA Objectives

This architecture defines the complete user-facing structure of Atlas at screen level.

Goals:

- clear navigation hierarchy
- explicit relationships between screens
- predictable movement between strategy, production, and delivery surfaces
- support both linear and non-linear workflows

## 2. Top-Level Structure

Atlas IA has three macro layers:

1. Orientation Layer
   - Home, Activity, global navigation
2. Production Layer
   - Projects, Studios, Assets, workflow surfaces
3. Governance Layer
   - Logs, Memory, Settings, Marketplace

## 3. Screen Definitions

Each screen includes: purpose, primary user, navigation path, relationships.

---

## 3.1 Home

Purpose:

- central launch surface for recent work, active priorities, and quick starts

Primary user:

- all users, especially returning users beginning a session

Navigation path:

- Sidebar -> Home
- Command -> Open Home

Relationships:

- links to Projects, Activity, and recommended workflows
- surfaces unresolved decisions from active projects

---

## 3.2 Projects

Purpose:

- list, create, filter, and organize projects across spaces

Primary user:

- solo builders, team leads, operators

Navigation path:

- Sidebar -> Projects
- Home -> Recent Projects

Relationships:

- parent node for all studio workspaces
- connected to Assets, Activity, and Publishing by project scope

---

## 3.3 Project Workspace (Container Screen)

Purpose:

- project-specific command center combining studios, assets, and progress

Primary user:

- active contributors within a project

Navigation path:

- Projects -> Select Project

Relationships:

- gateway to Research, Video, Image, Publishing, Agents, Memory, Logs
- hosts workspace layouts and studio switching

---

## 3.4 Assets

Purpose:

- unified asset library across types (text, media, briefs, outputs, references)

Primary user:

- creators, designers, producers, researchers

Navigation path:

- Sidebar -> Assets
- Project Workspace -> Assets tab

Relationships:

- consumed by all studios
- linked to Activity timeline, versions, and publishing targets

---

## 3.5 Research

Purpose:

- evidence gathering, synthesis, references, insight mapping

Primary user:

- strategists, writers, researchers, product teams

Navigation path:

- Sidebar -> Research
- Project Workspace -> Studio switcher -> Research

Relationships:

- upstream source for Product, Video, Image, and Campaign workflows
- outputs feed Memory and decision records

---

## 3.6 Video Studio

Purpose:

- planning and producing video-oriented deliverables from concept to publish package

Primary user:

- creators, marketers, media teams

Navigation path:

- Sidebar -> Video
- Project Workspace -> Studio switcher -> Video

Relationships:

- consumes Research and Assets
- feeds Publishing and Activity

---

## 3.7 Image Studio

Purpose:

- visual concepting, asset generation/curation, and brand-consistent output packaging

Primary user:

- designers, brand teams, creators

Navigation path:

- Sidebar -> Image
- Project Workspace -> Studio switcher -> Image

Relationships:

- connected to Design assets, style references, and Publishing channels

---

## 3.8 Publishing

Purpose:

- final packaging, checklist validation, channel targeting, and release state tracking

Primary user:

- operators, marketers, creators, PMs

Navigation path:

- Sidebar -> Publishing
- Project Workspace -> Publish step

Relationships:

- downstream of all production studios
- writes delivery outcomes to Activity and Logs

---

## 3.9 Marketplace

Purpose:

- discover and manage reusable workflow templates, component packs, and studio presets

Primary user:

- power users, team leads, admins

Navigation path:

- Sidebar -> Marketplace
- Command -> Browse marketplace

Relationships:

- templates can instantiate Projects and Workspaces
- governed by Settings and policy permissions

---

## 3.10 Settings

Purpose:

- configure preferences, accessibility, workspace behavior, integrations, notifications

Primary user:

- all users, with admin-specific sections

Navigation path:

- Sidebar -> Settings
- Profile menu -> Settings

Relationships:

- influences shell, command palette behavior, themes, and notification policy

---

## 3.11 Memory

Purpose:

- inspect reusable knowledge artifacts: decisions, playbooks, patterns, outcomes

Primary user:

- experienced users, team leads, knowledge managers

Navigation path:

- Sidebar -> Memory
- Project Workspace -> Context panel -> Memory

Relationships:

- receives material from Research, Activity, and completed workflows
- informs agent recommendations and workflow suggestions

---

## 3.12 Agents

Purpose:

- manage assistive participants, review contributions, tune participation scope

Primary user:

- all users, especially advanced operators

Navigation path:

- Sidebar -> Agents
- Command -> Open agent center

Relationships:

- connected to workflow steps and command palette suggestions
- references Memory, Assets, and Logs for explainability

---

## 3.13 Logs

Purpose:

- inspect operational and decision history for trust, debugging, and auditability

Primary user:

- advanced users, team leads, support, admins

Navigation path:

- Sidebar -> Logs
- Activity -> View details

Relationships:

- downstream trace of actions from all studios and publishing operations
- linked to error recovery and diagnostics surfaces

---

## 3.14 Activity

Purpose:

- chronological feed of project and workspace events with actionable summaries

Primary user:

- all users, especially collaborative teams

Navigation path:

- Sidebar -> Activity
- Status bar -> Open activity

Relationships:

- aggregates status from workflows, agents, and publishing
- entry point to Logs, Assets, and decision points

## 4. Cross-Screen Navigation Patterns

### 4.1 Primary Navigation

- sidebar for stable destinations
- studio switcher for production context changes
- project selector for scope changes

### 4.2 Secondary Navigation

- breadcrumbs for deep object hierarchy
- related-content links inside inspector and cards

### 4.3 Power Navigation

- command palette for direct jumps
- global search for object-level retrieval

## 5. Relationship Matrix

### 5.1 Upstream to Downstream

- Research -> Assets -> Studio Production -> Publishing -> Activity/Logs -> Memory

### 5.2 Systemic Connectors

- Settings affects all screens
- Agents and Memory augment all studios
- Activity and Logs provide cross-cutting traceability

## 6. Screen States

Every major screen supports:

- Empty state: guided entry and recommended first action
- Active state: normal operation with context panels
- Loading state: progressive skeleton and state hints
- Error state: diagnosis plus recovery pathways

## 7. IA Scalability Rules

1. New screens must map to an existing macro layer.
2. New navigation entries require a unique primary purpose.
3. No screen should duplicate another screen's core job.
4. Cross-links should reduce dead ends and preserve orientation.

## 8. IA Success Criteria

The architecture is successful when users can:

- locate any major function in under three navigation actions
- understand the current project/studio scope at all times
- move from research to publish without leaving Atlas
- audit what happened and why across the full journey