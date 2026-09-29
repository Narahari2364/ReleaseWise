# Release Versioning Policy

Owner: Release Engineering (#relops)

## Semantic versioning

All services use semantic versioning: `MAJOR.MINOR.PATCH` (for example `4.12.0`).

- **MAJOR:** breaking API changes. Requires an announcement to dependent teams at least
  2 weeks before release.
- **MINOR:** new backward-compatible features.
- **PATCH:** bug fixes and hotfixes only. No new features in a patch release.

## Release candidates

Before a MAJOR or MINOR release, a release candidate is tagged, e.g. `4.13.0-rc.1`.
The release candidate must run in staging for at least **24 hours** before it can be
promoted to production.

## Release notes

Every release must have release notes in the release tracker that include:
- the list of merged pull requests,
- any database migrations,
- any new feature flags and their default values,
- known issues.

## Release cadence

- web-frontend and search-indexer: weekly release train every Tuesday.
- auth-service and payments-api: every two weeks, on Wednesdays.
- Hotfixes: any time outside a freeze, following the Hotfix Checklist.
