# Hotfix Checklist

Owner: Release Engineering (#relops)
Use for urgent PATCH releases that fix a production issue.

- [x] Linked to an incident or a Sev-1/Sev-2 ticket
- [x] Change is minimal: bug fix only, no new features
- [ ] Reviewed by at least one engineer who is not the author
- [ ] Regression test added that reproduces the bug
- [ ] Shortened canary: 5% traffic for 10 minutes (instead of 30)
- [ ] Engineering Manager approval obtained if inside a freeze window
- [ ] Fix back-ported to the main branch after release
