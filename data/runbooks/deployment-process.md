# Deployment Process

Owner: Release Engineering (#relops)
Applies to: all production services (payments-api, auth-service, search-indexer, web-frontend)

## Overview

Every production deployment at Orbit goes through the same pipeline:
build -> staging -> canary -> full rollout. No service may skip the canary stage,
including hotfixes (hotfixes use a shortened canary, see the Hotfix Checklist).

## Deployment windows

- Standard deployments are allowed Monday to Thursday, 09:00 to 16:00 US Eastern.
- **Deployment freeze:** no deployments on Fridays after 12:00 ET, on weekends,
  or during the end-of-quarter freeze (last 3 business days of each quarter).
- Exceptions to a freeze require approval from the on-call Engineering Manager
  and must be logged in the #relops channel.

## Pipeline stages

1. **Build.** CI builds the container image and tags it with the release version
   (see the Release Versioning Policy). All unit and integration tests must pass.
2. **Staging.** The image is deployed to the staging cluster. Smoke tests run
   automatically. The release captain confirms the staging dashboard is green.
3. **Canary.** The new version receives **5% of production traffic for 30 minutes**.
   The canary is promoted only if:
   - error rate stays below 1%,
   - p99 latency does not rise more than 20% compared to the baseline,
   - no new Sev-1 or Sev-2 alerts fire.
4. **Full rollout.** Traffic is shifted in steps: 25%, 50%, 100%, with a
   10-minute hold at each step.

## Roles

- **Release captain:** the engineer running the deployment. Owns the go/no-go
  decision at each stage.
- **Approver:** a second engineer from the owning team who reviews the change log
  before the canary starts.

## Tooling

Deployments are triggered with the `orbit-deploy` CLI:

```
orbit-deploy start --service payments-api --version 4.12.0
orbit-deploy promote --service payments-api
orbit-deploy status --service payments-api
```

If anything looks wrong at any stage, stop and follow the Rollback Procedure.
