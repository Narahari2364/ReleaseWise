# On-Call FAQ

Owner: SRE team (#sre)

**Q: How long is an on-call shift?**
A: One week, Monday 10:00 ET to the following Monday 10:00 ET. Each team has a primary
and a secondary on-call engineer.

**Q: How fast do I need to acknowledge a page?**
A: Within 5 minutes. If the primary does not acknowledge within **10 minutes**, the page
automatically escalates to the secondary. If the secondary does not acknowledge within
another 10 minutes, it escalates to the Engineering Manager.

**Q: Who do I escalate to if I'm stuck?**
A: Escalation order: secondary on-call -> team Engineering Manager -> Director of Engineering.
For database problems, page the Database on-call directly using `/page db-oncall`.

**Q: How do I hand off my shift?**
A: Post a handoff note in #oncall-handoff before 10:00 ET Monday. Include open incidents,
ongoing investigations, and any noisy alerts that were silenced.

**Q: Can I silence a noisy alert?**
A: Yes, for up to 24 hours, using `orbit-alerts silence --alert <name> --hours <n>`.
You must open a ticket to fix the alert. Silences longer than 24 hours need approval from
the team lead.

**Q: Am I compensated for on-call?**
A: Yes. On-call engineers receive a weekly stipend, plus one day off in lieu if they were
paged outside business hours more than 3 times during the shift.

**Q: What if I get paged for a service I don't know?**
A: Check the service's runbook in the knowledge base first. If the runbook does not help
within 15 minutes, escalate. Nobody is expected to fix unfamiliar services alone.
