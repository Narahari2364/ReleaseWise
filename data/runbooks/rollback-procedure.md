# Rollback Procedure

Owner: Release Engineering (#relops)

## When to roll back

Roll back immediately (do not try to "fix forward") if any of these happen after
a deployment:

- Error rate exceeds 1% for more than 5 minutes.
- A Sev-1 incident is declared that may be related to the release.
- p99 latency rises more than 20% above baseline and does not recover within 10 minutes.
- Data corruption is suspected.

The release captain has authority to roll back without asking for approval.
**Rule of thumb: if you are unsure whether the release caused the problem, roll back first
and investigate second.**

## Target time

A rollback should be started within **15 minutes** of the problem being detected.

## Steps (stateless services: auth-service, web-frontend, search-indexer)

1. Announce in #relops: "Rolling back <service> from <new version> to <previous version>".
2. Run: `orbit-deploy rollback --service <service>`
   This shifts 100% of traffic back to the previous version in one step.
3. Watch the service dashboard for 10 minutes and confirm error rate and latency
   return to baseline.
4. Mark the release as `ROLLED_BACK` in the release tracker.
5. Open a follow-up ticket and schedule a blameless post-mortem within 3 business days.

## Steps (payments-api: stateful, extra care)

payments-api has database migrations, so a plain rollback may not be safe.

1. Announce in #relops and page the payments on-call engineer.
2. Check whether the release included a database migration
   (`orbit-deploy status --service payments-api --show-migrations`).
3. If **no** migration: follow the stateless steps above.
4. If there **was** a migration: do NOT run `orbit-deploy rollback` directly.
   First confirm the migration is backward compatible (see Database Migrations guide).
   If it is backward compatible, roll back the code only. If it is not, escalate to the
   Database on-call and the Engineering Manager before doing anything else.

## After a rollback

- The failed version may not be redeployed until the root cause is identified.
- Add a regression test that reproduces the failure before the fix is released.
