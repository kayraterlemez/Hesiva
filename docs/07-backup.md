# Backup System

## Purpose

The backup system protects Hesiva customer and financial history from software errors, user mistakes, operating-system problems, and hardware failure.

Backup is a core Version 1 feature.

A backup is considered useful only if it can be verified and restored.

---

# Backup Philosophy

The backup system follows these principles:

- SQLite-safe snapshots
- Simple manual backup
- Automatic recovery points
- Multiple generations
- Clear destination
- Restore verification
- No cloud dependency
- No Internet requirement

The user should not need database knowledge to create or restore a backup.

---

# Backup Destination Setup

During initial application setup, Hesiva should ask the user to choose a preferred backup destination.

The interface should recommend a location on a different physical device when one is available, such as:

- External SSD
- External HDD
- USB storage
- Local NAS/mounted network storage when intentionally configured

The application must still be usable if an external destination is not available.

A local fallback directory may be used, but the UI should make clear that a backup stored on the same physical disk does not protect against failure of that disk.

Default local fallback locations:

Linux:

```text
~/.local/share/hesiva/backups/
```

Windows:

```text
%LOCALAPPDATA%\Hesiva\Backups\
```

The user may change the destination later.

---

# Backup Types

## Manual Backup

The user can create a backup at any time.

The normal workflow should require only a small number of actions:

```text
Backup
↓
Create Backup
↓
Choose/confirm destination
↓
Verified backup completed
```

---

## Automatic Backup

Automatic backups should create useful recovery points without producing unnecessary copies on every application open/close.

Recommended Version 1 policy:

- At most one normal automatic backup per day when the application is used
- Always create an appropriate recovery backup before a significant database migration
- Create a recovery backup before legacy import when an existing database contains data
- Create a recovery backup before restore

Exact scheduling may be adjusted during implementation, but startup **and** shutdown backups on every run are not required.

---

# SQLite-Safe Snapshot

The application must not create its primary database backup by blindly copying an active SQLite database file.

SQLite may use WAL or journal files, and a raw copy can miss committed data or create an inconsistent snapshot.

The database snapshot should use SQLite's Online Backup API or an equivalent SQLite-supported safe backup mechanism.

Conceptually:

```text
Live SQLite database
        ↓
SQLite Online Backup API
        ↓
Temporary database snapshot
        ↓
Integrity verification
        ↓
Backup archive
```

The temporary snapshot, not the actively open database file, is packaged into the final archive.

---

# Backup Contents

A normal backup archive contains:

```text
database.sqlite
config.json
metadata.json
```

`database.sqlite` contains all business entities including customers, transactions, animals, and reminders.

`config.json` is the validated real application configuration snapshot. It contains the encoded
Argon2id password hash and setup-completion state but never a plain-text password. The encoded hash
is copied unchanged; backup creation does not rehash it.

`metadata.json` contains compatibility and verification metadata.

Temporary WAL, SHM, cache, log, or build files are not part of the archive.

---

# Backup Format

Version 1 uses a single ZIP archive for portability and inspection.

The implemented archive is stored without an additional compression policy and contains exactly
`database.sqlite`, `config.json`, and `metadata.json`. The database member is produced with
SQLite's Online Backup API, not by copying the active `hesiva.db` file. Metadata records the
backup format, Hesiva version, current Alembic revision, creation time, database size, and a
SHA-256 checksum.

Example filename:

```text
hesiva_backup_2026-08-07_0105.zip
```

A timestamp prevents accidental filename reuse.

If an identical name already exists, the application must not silently overwrite the existing backup.

---

# Metadata

Backup metadata should contain enough information for safe restore.

Recommended fields:

- Hesiva application version
- Database schema version
- Backup creation timestamp
- Backup format version
- Operating system
- Database file size
- Optional checksum(s)

Metadata must not contain unnecessary customer information.

---

# Backup Verification

A backup is not successful merely because a ZIP file exists.

Verification should include:

1. ZIP/archive integrity.
2. Required files exist.
3. Database can be opened.
4. SQLite integrity check succeeds, preferably `PRAGMA quick_check` or stronger when appropriate.
5. Metadata is readable.
6. Backup/schema version is supported.
7. Optional checksums match when present.

Only after verification succeeds should the UI display a successful-backup message.

---

# Backup Retention

The application should keep multiple backup generations.

A reasonable starting policy is:

- 7 recent daily backups
- 4 weekly backups
- 12 monthly backups

Retention must never delete the only known valid backup.

Retention logic must operate only inside a configured Hesiva backup destination and must never delete unrelated files.

External/manual backups may be excluded from automatic retention when appropriate.

---

# Restore Process

Restore follows a defensive process:

```text
User selects backup
        ↓
Validate archive
        ↓
Validate contained SQLite database
        ↓
Create safety backup of current database and configuration
        ↓
Close active database sessions
        ↓
Extract selected backup to temporary location
        ↓
Verify extracted database again
        ↓
Publish the replacement database and configuration as one logical snapshot
        ↓
Reinitialize/restart application
        ↓
Verify restored database and configuration
```

The current database must not be destroyed before the selected replacement has passed validation.

The current Version 1 restore accepts only a verified archive whose contained database is already
at the Alembic head bundled with the running Hesiva version. Older and unknown revisions are
rejected; restore does not silently migrate them. Before replacement, Hesiva creates and preserves
a verified safety archive containing the current database and current valid configuration in the
local `backups` directory. The staged database and configuration are each complete and durable
before pair publication. After publication, the application context is rebuilt and database-derived
Main Window state is cleared and reloaded in process.

The selected archive remains source-only. Restore publishes both `database.sqlite` and
`config.json`; the password from the restored snapshot is subsequently required. If either pair
publication, database reopening, or post-publication validation fails, Hesiva rolls both live files
back from the safety archive. A mixed old/new pair is never reported as success. A rollback failure
is reported as a severe recovery error and the safety archive is retained.

---

# Restore Failure

If restore fails before replacement, the current database remains untouched.

If a failure occurs during replacement, the application must use the safety copy/recovery strategy to avoid leaving the user without a working database.

The restore workflow should prefer atomic rename/replace operations where supported.

---

# Backup Compatibility

Newer Hesiva versions should restore older supported backup formats whenever practical.

If migration is required after restoring an older database:

```text
Restore
↓
Verify
↓
Create appropriate recovery point if needed
↓
Run schema migration
↓
Verify
```

Unsupported future/unknown backup formats should be rejected with a clear explanation rather than guessed.

---

# Configuration Recovery

Version 1 restores the validated archived `config.json` together with its database. This preserves
the password hash exactly and makes the restored snapshot's password authoritative. Unknown valid
configuration fields are preserved by normal credential updates. Any future machine-specific
configuration field must define its own revalidation rule before being added to this format.

---

# Backup Destination Unavailable

If the configured external backup destination is unavailable:

- Normal application use should not become impossible.
- The user should receive a clear warning.
- A local fallback backup may be created when configured/appropriate.
- The application should not falsely report the external backup as successful.

---

# Recovery Rehearsal

Before production use, the complete backup/restore cycle must be tested with representative data.

A backup system is not considered trusted until a successful restore has been demonstrated.

---

# Import Protection

Version 1 legacy import is primarily intended for an empty Hesiva business database.

If an existing Hesiva database contains business data and an operation may modify it, an appropriate recovery backup is required before proceeding.

The original legacy source remains independent and read-only.

---

# Security

Backups contain business data and must be treated as sensitive.

Version 1 backup archives are not necessarily encrypted.

Users should store backups in appropriately protected locations.

Encrypted backup archives may be considered in a future version.

---

# Future Improvements

Possible future improvements include:

- Encrypted backup archives
- External-drive detection
- Backup history viewer
- Scheduled reminders for missing external backups
- Additional integrity/checksum reporting

These are not required for Version 1.

---

# Backup Principles

1. Never rely on a raw copy of an active SQLite database.
2. Verify every backup before reporting success.
3. Never overwrite the only valid backup.
4. Keep multiple generations.
5. Prefer a different physical device for hardware-failure protection.
6. Create recovery points before risky database operations.
7. Test restore before trusting the system.
8. Keep the workflow simple enough for daily use.

A backup file that cannot be restored is not a successful backup.
