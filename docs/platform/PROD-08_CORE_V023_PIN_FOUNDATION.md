# PROD-08: Core v0.2.3 Exact Pin Foundation

**Timestamp:** 2026-08-11T22:28:32Z
**Phase:** G03 — PLATFORM CONSUMER PROOF / R3
**Target Repository:** `natbkgift/flowbiz-ai-platform`

---

## 1. Executive Summary

PROD-08 installs the manually published `flowbiz-ai-core` v0.2.3 wheel as the
runtime schema source for the Platform-to-runner boundary. Verification and
release publication are manual and do not depend on GitHub Actions.

---

## 2. Core Pin Specification

* Core package: `flowbiz-ai-core`
* Core version constraint: `0.2.3`
* Core verified commit: `a62027e435197f604dca22913c2a8a33705e1492`
* Release tag: `v0.2.3`
* Wheel SHA-256: `98ffd438eea9c41f229cc7c7e38476c05460849ef534eb9859da70c50f9ec440`
* Manual release publication: `COMPLETE`
* GitHub Actions required: `NO`
* Posture: `runtime-installed`

---

## 3. Verification

Platform consumer tests assert the exact optional runtime pin, installed
distribution version, and v1.0 contract import. Container builds accept only the
published v0.2.3 wheel at the fixed artifact path; deployment separately verifies
its digest before building.
