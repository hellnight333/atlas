# Atlas Blueprint 08: Command Palette

## Purpose

Blueprint Command Palette as the execution-first keyboard control surface with clear boundary from Search, Quick Switcher, and Mission Control.

## Primary Users

- Expert keyboard-first users
- Intermediate users accelerating routine operations
- Beginners using guided natural-language invocation

## Governing References

- COMMAND_SYSTEM.md
- COMMAND_PALETTE.md
- UNIVERSAL_SEARCH.md
- DESKTOP_SHELL_V1.md
- LONG_SESSION_UX.md

## ASCII Layout

```text
+--------------------------------------------------------------------------------------+
| COMMAND PALETTE [Mode: Command | Search | Quick Action | AI] [Scope: Global/Project]|
+--------------------------------------------------------------------------------------+
| INPUT LINE: verb object modifiers / natural language intent                          |
+-----------------------------+------------------------------------+-------------------+
| CANDIDATE COMMANDS          | RECENT COMMANDS                    | PINNED COMMANDS   |
| - ranked executable actions | - outcome-annotated history        | - user anchors    |
+-----------------------------+------------------------------------+-------------------+
| CONTEXT PREVIEW + IMPACT: why command, affected scope, safety notes, next steps     |
+--------------------------------------------------------------------------------------+
```

## Components

- Mode selector (Command/Search/Quick Action/AI)
- Scope selector
- Input line
- Candidate commands list
- Recent commands list
- Pinned commands list
- Context and impact preview

## Navigation

- execute selected command in current or explicit scope
- handoff to Universal Search only when retrieval intent dominates
- open Quick Switcher from mode pathway for context-only jumps

## Keyboard Shortcuts

- open/close Command Palette
- mode cycle
- candidate list navigation and execute
- pin/unpin command
- chain command steps

## Mouse Interactions

- click mode chips and scope selectors
- click command entries and preview details
- pin/unpin and reorder pinned command set

## AI Behaviors

- natural-language to structured command mapping
- explain "why this command" and impact prediction
- suggest command chains from repeated patterns

## Empty State

No history or pinned commands:

- starter command examples by current context
- common command categories shortcut list

## Busy State

Under heavy background activity:

- command candidates prioritize safe operations
- high-impact commands show additional guard notes

## Error State

Failed command invocation:

- classify failure reason (scope, permission, dependency, transient)
- show one-step remediation and retry path

## Responsive Behavior

- preview panel collapses under compact width
- mode and scope selectors remain persistent in compact header
- candidate list remains primary in all sizes

## Accessibility Notes

- full keyboard operation for mode/scope/input/candidates
- deterministic focus retention after execution
- assistive-friendly command intent and error explanation text

## Future Expansion

- enterprise role-aware command visibility
- plugin command namespaces with trust labels
- adaptive command macros and team-shared command packs

## Ambiguity Notes

- command alias conflict resolution strategy across plugin and core namespaces requires explicit namespace precedence policy in future command governance appendix.