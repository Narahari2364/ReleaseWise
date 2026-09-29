# Post-Deploy Verification Checklist

Owner: Release Engineering (#relops)
Use after full rollout reaches 100%.

- [x] Error rate below 1% for 15 minutes after full rollout
- [x] p99 latency within 20% of baseline
- [x] Smoke tests pass against production
- [ ] No new Sev-1 or Sev-2 alerts since the deployment started
- [ ] Key business metric (e.g. payments success rate) unchanged
- [ ] Release marked as DEPLOYED in the release tracker
- [ ] Deployment announced as complete in #relops
