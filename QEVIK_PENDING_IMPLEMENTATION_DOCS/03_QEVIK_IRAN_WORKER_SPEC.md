# QEVIK IRAN WORKER SPECIFICATION

## Purpose

Provide genuine Iran-origin browsing/crawling and verification.

## Why it exists

A site may:
- work from Europe
- fail from Iran
- show different content in Iran
- have CDN/WAF differences
- have regional restrictions

Qevik must not infer Iran accessibility from a foreign server.

## Architecture

Qevik Core:
- creates verification job
- sends target and test instructions
- receives structured result

Iran Worker:
- physically/network-wise operates from Iran
- runs browser and HTTP checks
- returns evidence

## Required tests

### HTTP
- DNS resolution
- TCP/TLS connection
- HTTP status
- redirects
- response timing

### Browser
- Chromium navigation
- JavaScript execution
- screenshots
- console errors
- network failures
- key element presence

### Crawl
- page discovery
- selected URL checks
- robots behavior
- canonical URLs
- asset loading

## Result schema

At minimum:

- target
- timestamp
- origin = Iran
- reachable
- HTTP status
- browser success
- screenshot
- failure category
- evidence
- worker version

## Security

The Iran worker must:
- authenticate to Qevik Core
- receive scoped jobs
- never expose arbitrary shell access
- store secrets securely
- report worker health
- support revocation

## Acceptance

Run the same target from:
1. Hetzner
2. Iran Worker

Return a comparison showing actual observed differences.
