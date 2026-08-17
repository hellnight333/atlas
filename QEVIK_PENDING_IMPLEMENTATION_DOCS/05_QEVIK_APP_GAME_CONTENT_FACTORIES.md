# QEVIK APP / GAME / CONTENT FACTORIES

## Purpose

Extend the same execution model beyond websites.

## App Factory

Pipeline:
request
→ requirements
→ architecture
→ implementation
→ tests
→ build
→ deployment/package
→ verification
→ delivery

Must support:
- web apps
- dashboards
- internal tools
- APIs
- mobile/web-ready applications where supported

## Game Factory

Pipeline:
concept
→ game design
→ technical plan
→ asset plan
→ implementation
→ build
→ test
→ package
→ preview/demo

Do not claim a platform is supported until an actual build test passes.

## Content Factory

Pipeline:
brief
→ research
→ script/content plan
→ asset acquisition/generation
→ assembly
→ quality checks
→ publishing
→ verification

Possible outputs:
- images
- short videos
- articles
- social content
- marketing assets

## Common requirements

Every factory must use:
- project IDs
- execution IDs
- artifact registry
- Git where code is involved
- worker dispatch
- approval policy
- retry/resume
- verification
- final report

## Acceptance

Each factory needs one automated end-to-end fixture before being marketed as production-ready.
