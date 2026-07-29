# Backup And Recovery

Production RDS keeps 30 days of encrypted automated backups and runs multi-AZ. ElastiCache keeps 14
days of snapshots and uses automatic failover. S3 artifacts are encrypted, private, versioned, and
retain noncurrent object versions for 90 days.

## Database Backup

Create a portable encrypted-at-rest backup in a protected operator workspace:

```bash
export AEAI_DATABASE_URL='postgresql+psycopg://...'
python scripts/manage_recovery.py backup --output /secure/aeai-$(date +%F).dump
```

The command writes a checksum manifest next to the dump. Upload both files to the restricted recovery
bucket and verify the recorded SHA-256 after transfer.

## Restore Drill

Create an isolated empty database whose name contains `restore_drill`, then run:

```bash
export AEAI_RESTORE_DATABASE_URL='postgresql+psycopg://.../aeai_restore_drill'
python scripts/manage_recovery.py restore-drill --backup /secure/aeai-YYYY-MM-DD.dump
```

Validate migrations, run counts, artifact metadata, workflow events, and a read-only UI inspection.
Record elapsed time and the newest restored record. Run this drill monthly in staging.

## Regional Recovery

Provision the Terraform stack in the recovery region, restore RDS from the latest cross-region copied
snapshot, restore Redis only when queue recovery is required, and configure the runtime secret with
the recovered endpoints. Replicate or restore versioned S3 objects, deploy the exact release image,
then execute health, security, connector, and workflow checks before DNS failover. The drill passes
when the newest durable metadata is within the 15-minute RPO and service is usable within the 60-minute
RTO. Exercise this procedure quarterly and attach timestamps and resource identifiers to the release
evidence.
