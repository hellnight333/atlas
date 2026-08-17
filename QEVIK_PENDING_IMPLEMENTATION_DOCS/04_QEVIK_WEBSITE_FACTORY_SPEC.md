# QEVIK WEBSITE FACTORY SPECIFICATION

## Goal

A user can request a complete website and receive a deployed, verified result without manually moving work between tools.

## Input

Example:
"Create a modern website for a Dubai restaurant. Include menu, contact, location, WhatsApp CTA and responsive mobile design. Publish it."

## Pipeline

### 1. Intake
Create project and execution ID.

### 2. Discovery
Collect:
- business information
- target audience
- brand assets
- requirements
- domain/hosting information

### 3. Research
Use browser/web research where authorized.

### 4. Specification
Generate:
- sitemap
- page requirements
- content requirements
- design direction
- technical stack

### 5. Implementation
Coding agent creates project.

### 6. Assets
Use:
- supplied assets
- permitted external assets
- generated assets
- placeholders when necessary

Record provenance.

### 7. Quality
Run:
- build
- lint
- typecheck
- tests
- accessibility checks
- responsive checks
- broken-link checks

### 8. Deployment
Deploy to configured provider.

### 9. Verification
Open public URL in browser and verify:
- HTTP
- page load
- JavaScript
- navigation
- forms/CTAs
- mobile layout
- key content

### 10. Delivery
Return:
- URL
- project
- Git commit
- screenshots
- deployment record
- verification result

## Failure handling

If deployment fails:
- preserve build logs
- identify cause
- retry safe operations
- do not silently report success

## Acceptance test

A fictional business website must go from natural-language request to publicly reachable verified site with no manual copy/paste.
