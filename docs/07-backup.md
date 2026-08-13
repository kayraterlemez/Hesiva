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

Version 1 policy:

- After authentication/setup succeeds, startup checks the controlled local
  `<application-data>/backups` directory once per application run.
- At most one verified normal automatic backup is created per local calendar day.
- Normal automatic names use `hesiva_auto_YYYY-MM-DD_HH-MM-SS.zip`, with a numeric no-clobber
  suffix only when the exact timestamp name is already occupied.
- The optional manual-backup destination is never used as an automatic fallback.
- Failure is non-blocking, is not retried in the same run, and is reported after the Main Window is
  available with a recommendation to create a manual backup.
- Recovery backups before significant migration, legacy import, and restore remain separate safety
  workflows.

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
is copied unchanged; backup creation does not rehash it. It also preserves the optional preferred
manual-backup directory in `backup.destination_directory`.

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
Hesiva therefore creates the selected destination exclusively and streams the already verified
archive into that new file. This portable no-clobber publication deliberately does not claim to be
an atomic rename: a write failure or abrupt process termination can leave an incomplete file at the
newly selected name. Such a file is never reported as a successful backup and normal validation
rejects it; it never replaces a pre-existing backup.

The live database, configuration, application lock, restore-recovery marker, and SQLite sidecar
names in the application-data directory are reserved infrastructure paths and cannot be selected as
manual backup destinations.

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

After a new automatic backup has been created and independently validated, Hesiva retains verified
normal automatic backups for the most recent 30 local calendar days. Cleanup recognizes only the
exact `hesiva_auto_...zip` namespace, rejects symlinks, validates each archive, and verifies that the
candidate did not change during validation before deletion. The archive metadata creation instant
must also match the local date/time encoded in the automatic filename, and multiply-linked files
are treated as ambiguous. Corrupt, renamed, hard-linked, and otherwise ambiguous lookalikes are not
deleted and cannot suppress that day's real automatic backup.

Manual `hesiva_backup_...zip` files, restore `hesiva_safety_before_restore_...zip` files, arbitrary
ZIP files, and unrelated files are never part of automatic retention. Because the new verified
archive exists before cleanup starts, retention never removes the only known valid automatic
backup. A cleanup failure is logged and does not turn the already-successful new backup into a
startup failure or trigger broader deletion.

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

Before publishing either live file, Hesiva durably records the verified pre-restore safety archive
in the application-data directory. If the process stops after that boundary, the next exclusively
locked startup restores the prior database/configuration pair from that archive and then removes the
recovery marker. A missing, modified, or malformed recovery archive/marker blocks startup rather
than guessing which half of a pair is authoritative.

If a restore attempt cannot prove that a partially published recovery marker was removed durably,
the current application context stops accepting business operations and the Main Window closes.
It does not begin another database/configuration rollback after the restored pair has already been
published and validated. On the next exclusively locked startup, a surviving marker restores the
prior pair; if the marker deletion persisted, the already-consistent restored pair remains in use.
The application never continues accepting changes that a pending recovery marker could later roll
back.

Restore also fails closed before live-database replacement when any SQLite sidecar directory entry
remains after Engine shutdown, including a dangling symbolic link, or when sidecar state cannot be
inspected safely.

Backup validation rejects unexpected executable SQLite schema objects, broken foreign keys,
cross-customer animal/transaction links, invalid required values/date encodings, and non-integer
kuruş values. Archive, ZIP entry-count/central-directory, member, configuration, row, and text
resource ceilings bound local hostile or pathological input before Python's ZIP reader materializes
the archive directory or any candidate is published.

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
configuration fields are preserved by normal credential and Settings updates. The restored
`backup.destination_directory` is preserved unchanged even when it names a directory unavailable on
the current machine. Its structural validity is separate from current availability.

---

# Backup Destination Unavailable

If the configured external backup destination is unavailable:

- Normal application use should not become impossible.
- Authentication and business-data access continue normally.
- A manual backup attempt fails with a clear warning.
- Hesiva does not silently fall back or report success.
- The user may select another preferred directory in Settings.

Missing `backup` configuration or a `null` destination uses the established local application-data
`backups` directory. Internal safety backups created during restore continue to use that controlled
local directory regardless of the preferred manual-backup destination.

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
