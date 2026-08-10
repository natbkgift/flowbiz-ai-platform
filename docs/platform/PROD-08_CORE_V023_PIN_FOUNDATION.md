# PROD-08: Core v0.2.3 Exact Pin Foundation

**Timestamp:** 2026-08-10T21:15:00Z
**Phase:** G03 — PLATFORM CONSUMER PROOF / R3
**Target Repository:** `natbkgift/flowbiz-ai-platform`

---

## 1. Executive Summary

PROD-08 records the approved Platform release constraint for `flowbiz-ai-core` v0.2.3 without installing the private Core repository in Platform CI.

---

## 2. Core Pin Specification

* Core package: `flowbiz-ai-core`
* Core version constraint: `0.2.3`
* Core verified commit: `9576229ce600caab54b9d4590dee3f86fc9145f0`
* Private Core install in Platform CI: `DEFERRED`
* Package registry publication: `NOT_PERFORMED`
* Posture: `constraints-only`

---

## 3. Verification

Platform consumer tests assert that `pyproject.toml` remains clean of direct private dependency references while registering the verified release constraint `flowbiz-ai-core==0.2.3`.
