# Incident Response & Severity Levels

Owner: SRE team (#sre)

## Severity levels

| Severity | Definition | Example | Response time |
|---|---|---|---|
| Sev-1 | Full outage or data loss for customers | payments failing for all users | 5 minutes, 24/7 |
| Sev-2 | Major feature degraded, workaround exists | search results slow for 30% of users | 15 minutes, 24/7 |
| Sev-3 | Minor issue, limited customer impact | an admin page throws errors | next business day |
| Sev-4 | Cosmetic or internal-only issue | typo in an internal dashboard | best effort |

## Declaring an incident

1. Anyone can declare an incident. Run `/incident declare` in Slack.
2. Choose the severity. When unsure, pick the higher severity; it can be downgraded later.
3. A dedicated channel `#inc-<date>-<short-name>` is created automatically.

## Roles during an incident

- **Incident Commander (IC):** coordinates the response and makes decisions. For Sev-1,
  the IC must be a senior engineer or Engineering Manager.
- **Communications lead:** posts status updates. For Sev-1, updates go out
  **every 30 minutes** on the public status page.
- **Subject-matter experts:** engineers from the affected service teams.

## Resolution

- An incident is resolved when customer impact has stopped, not when the root cause is fixed.
- Every Sev-1 and Sev-2 incident requires a blameless post-mortem, published within
  5 business days.
