# Pre-Release Checklist

Owner: Release Engineering (#relops)
Use before starting any production deployment. The release captain ticks each item.

- [x] All CI checks (unit, integration, lint) are green on the release commit
- [x] Release version tagged following the Release Versioning Policy
- [x] Release notes written in the release tracker
- [x] Change log reviewed by an approver from the owning team
- [ ] Database migrations (if any) approved by the Database team
- [ ] Release candidate has run in staging for at least 24 hours (MAJOR/MINOR only)
- [ ] New feature flags default to OFF
- [ ] Confirmed the deployment is not inside a freeze window
- [ ] On-call engineer for the service is aware of the deployment
- [ ] Rollback plan confirmed (previous version available, migration is backward compatible)
