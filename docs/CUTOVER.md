# Data, traffic cutover and rollback

This is a required customer-owned runbook, not an automatically executed operation. Fill in owners, measurable acceptance criteria, maintenance windows, RTO/RPO and the existing EC2 rollback endpoint before production approval.

## Before migration

Inventory source/target dependencies and capture backups with a tested restore. Keep databases external to replaceable pods unless a separately designed stateful migration is approved. Plan replication, schema compatibility, validation and reconciliation. Do not copy live EC2 disk files into a container and assume consistency. Resolve in-memory sessions, host-bound licenses, Windows services, cron/background-job ownership, local writable paths, ports and external allowlists.

Document the intended DNS/load-balancer/gateway mechanism and whether weighted routing is supported. Reduce TTL ahead of time if DNS is used, accounting for resolver caches. Create TLS/gateway access through your platform standard. The kit intentionally creates ClusterIP services only and never silently changes a source routing resource.

## Controlled cutover

1. Confirm application artifact, source commit and image digest match staging; record the Azure DevOps run and Ops approval.
2. Confirm backups, sync lag and data validation meet RPO; enforce any maintenance/read-only window. Disable duplicate job execution using an application-approved lease/fencing design.
3. Validate target business journeys and dependency access, then send a small approved share of traffic if the gateway supports it. Observe defined latency/error/business metrics, not just pod readiness.
4. Increase traffic only when the agreed observation window passes. Account for long-lived connections, DNS caches and session affinity.
5. Keep the EC2 rollback path and data compatibility intact for the agreed retention window. Decommission EC2s only through a separate approved change after stability, backup retention and cost review.

## Rollback

Specify the exact previous routing configuration and previously deployed image revision. An Ops/DevOps engineer can reject a pending release; Helm restores the previous target revision on deployment/smoke failures as described in RUNBOOK.md. After traffic cutover, restore routing to the EC2 endpoint through the same reviewed gateway/DNS mechanism, and stop duplicate workers.

Data rollback is separate: reconcile writes that reached EKS, handle incompatible schemas and prevent split-brain. Do not blindly restore an old database over new production writes. Run the documented restore/reconciliation procedure, verify business data and resume traffic only after the owner accepts the result.

Stop migration and report blocked if the data owner cannot provide a consistent transfer/rollback plan. Retaining the original EC2 does not itself guarantee rollback when external data has changed.
