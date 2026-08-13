# Security

## Purpose

The security model protects Hesiva business data from unauthorized application access, accidental disclosure, corruption, and unsafe implementation practices.

Hesiva is a local, offline-first desktop application. It is not designed to expose customer data to the Internet.

Security must remain understandable and must not create unnecessary risk to data recovery.

---

# Security Philosophy

Hesiva follows these principles:

- Local-first
- Offline-first
- No cloud dependency
- No telemetry
- No advertising
- No user tracking
- No online authentication
- No unnecessary background network services
- Data integrity before unnecessary complexity

Normal application operation requires no Internet connection.

---

# Authentication

On first launch, the user creates and confirms a local application password.

The password is persisted before the initial empty-database/Veresiye 5 import choice, with setup
marked incomplete. Cancelling or failing that choice does not discard the credential. The next
launch authenticates with the same password and resumes setup. If an import completed but final
setup-state publication failed, the populated database plus valid incomplete credential is safely
finalized after login without importing again.

On later launches, successful password authentication is required before normal access.

After login, Version 1 remains unlocked until the application is closed.

Automatic inactivity locking is not required for Version 1.

---

# Password Storage

Passwords must never be stored in plain text.

Argon2id is the required Version 1 password hashing algorithm. Production uses the maintained
`argon2-cffi` high-level `PasswordHasher` with explicit parameters:

- Type: Argon2id
- Time cost: 3
- Memory cost: 65536 KiB
- Parallelism: 4
- Hash length: 32 bytes
- Salt length: 16 bytes

A maintained library shall generate appropriate salts and parameters.

The application shall store only the resulting password hash and required algorithm metadata.

The original password must not be recoverable.

The single credential/configuration store is `config.json` in the per-user Hesiva application-data
directory. Its required Version 1 shape is:

```json
{
  "format_version": 1,
  "authentication": {
    "password_hash": "<valid encoded Argon2id hash>",
    "setup_complete": true
  },
  "backup": {
    "destination_directory": null
  }
}
```

The `backup` object is optional for backward-compatible reads. Its destination is `null` or a
nonblank absolute path. Structural validation does not require that a configured external directory
is currently mounted: an unavailable but structurally valid destination is not credential
corruption and does not block authentication or normal data access. Settings never displays the
password hash or authentication internals.

`setup_complete` is `false` after password creation until the empty/import choice completes. Writes
use a fully written and fsynced same-directory temporary file, restrictive permissions, atomic
replacement, and POSIX parent-directory fsync. On POSIX the application-data directory is `0700`
and `config.json` is `0600`.

Missing configuration is legitimate only for a fresh empty business database. Missing, malformed,
or unusable authentication configuration with a populated current database blocks startup without
modifying the database. A valid encoded password hash with `setup_complete=false` is an incomplete,
recoverable setup rather than corruption.

Version 1 has no password reset, forgotten-password recovery, security question, recovery code,
hint, default password, or backdoor.

---

# What the Application Password Protects

The application password is application-level access control.

It prevents normal access through the Hesiva interface without authentication.

It does **not** encrypt the SQLite database.

A person who already has sufficient operating-system/filesystem access may be able to read the database outside Hesiva.

The application must not imply otherwise.

Database-at-rest encryption is outside Version 1 unless a later explicit decision changes the scope.

---

# File Permissions

Application data should be stored inside the current operating-system user's application-data directory.

Files should use restrictive permissions where practical.

Users should also protect the operating-system account with an appropriate password.

Physical theft and full compromise of the operating-system account cannot be solved by the Hesiva login screen alone.

---

# Sensitive Data Locations

Business data should not be duplicated unnecessarily.

Customer or financial information must not be copied into:

- Debug logs
- Crash messages
- Temporary diagnostic files
- Cache files without a documented need

However, some intentional outputs contain business data by design:

- SQLite database
- Verified backups
- Printed/PDF account statements
- User-requested exports

These files must be treated as sensitive business records.

The statement "sensitive information only exists inside the database" must not be used because backups and reports are legitimate copies.

---

# Input Validation

All business input must be validated.

Validation includes:

- Required customer names
- Required transaction descriptions
- Valid dates
- Exact money parsing
- Non-zero transactions
- Valid customer relationships
- Animal ownership
- Reminder dates
- Import source structure

UI validation improves usability, but authoritative business validation belongs in the service layer.

---

# Money Safety

Financial values must not use binary floating-point storage.

Money is stored as signed integer kuruş.

Normal payment UI input is positive and is converted to a negative stored movement by the business layer exactly once.

This avoids accidental double-negation and rounding problems.

---

# SQL Safety

SQLAlchemy or bound SQL parameters shall be used.

Untrusted user text must never be concatenated directly into executable SQL.

Database access remains inside repository/database infrastructure as defined by the architecture.

---

# Database Transactions

Logical write operations must be atomic.

A failure must not leave half-completed business data.

Hesiva enforces one live owner for each application-data directory. The lock covers startup
recovery, the SQLAlchemy Engine lifetime, backup/restore publication, and shutdown. A crashed local
owner's stale lock is recoverable; a live owner is never evicted merely because time passed.

SQLite foreign key enforcement must be enabled.

Important financial history must not be physically deleted by accidental cascade behavior.

---

# Historical Data Protection

Normal application behavior uses:

- Customer archive
- Animal archive
- Transaction void
- Reminder completion

Voiding a financial movement removes it from active calculations but preserves the record.

Hard deletion of important financial history is not a normal Version 1 operation.

---

# Error Handling

User-facing errors should be understandable and should not expose unnecessary internal details.

Raw stack traces, SQL statements, internal exceptions, or secret values should not be shown in normal dialogs.

Technical details may be logged when safe.

Database and report failures are logged by operation and exception type only at UI boundaries.
Raw exception strings and tracebacks are not logged there because SQLAlchemy errors can embed bound
customer/financial values and filesystem errors can embed customer-derived report paths.

---

# Logging

Logs exist for diagnostics.

Logs must not contain:

- Passwords
- Password hashes
- Full customer histories
- Full customer notes
- Complete financial records
- Unnecessary personally identifying customer data

Logs may contain technical identifiers and aggregate/error context when needed for troubleshooting.

Log rotation should prevent unbounded growth.

---

# Backup Safety

Backups are security- and integrity-sensitive files.

The application must:

- Use a SQLite-safe backup mechanism
- Verify the database snapshot
- Avoid overwriting the only valid backup
- Keep multiple generations
- Create recovery points before risky operations
- Clearly identify backup destination and result

A backup on the same physical disk is useful for software/user mistakes but is not sufficient protection against disk failure.

---

# Restore Safety

Restore must be defensive.

Before replacing current data, the application should:

1. Verify the selected archive.
2. Verify the contained SQLite database.
3. Create a safety backup of the current working database.
4. Close active database sessions.
5. Replace data using a controlled/atomic strategy.
6. Verify the restored database.
7. Reinitialize or restart the application.

A failed restore must not destroy the working database.

---

# Import Safety

Legacy sources must be opened read-only.

The importer must never modify the original `.exa` or `.edb` source.

Version 1 legacy migration is intended for an empty Hesiva business database.

Critical import errors must roll back the migration.

Legacy stored balances are reconciliation data, not authoritative current balances.

---

# Backup and Import Files

Temporary files used for archive extraction, backup snapshots, or legacy migration must be placed in controlled temporary directories.

They should be removed after successful completion when no longer needed.

Cleanup failure must not be treated as permission to delete the original source or current production database.

---

# Software Updates

Updates are manual.

Hesiva shall not require an online update service for normal operation.

Updates should be infrequent and justified by:

- Critical security fixes
- Data-integrity fixes
- Serious bugs
- Explicitly planned stable improvements

Important database migrations require a recovery backup before execution.

---

# Third-Party Dependencies

Dependencies should be minimized and reviewed.

A production dependency should be:

- Maintained
- Widely used or otherwise well justified
- Compatible with supported Python versions
- Compatible with Linux and Windows where relevant
- Appropriate for the target hardware

Custom cryptography must not be implemented.

---

# Network Behavior

Version 1 does not require network access for:

- Authentication
- Database use
- Backup
- Restore
- Reports
- Reminders
- Legacy import

No telemetry or automatic customer-data transmission is permitted.

---

# Future Security Improvements

Possible future improvements include:

- Optional database-at-rest encryption
- Encrypted backup archives
- Additional integrity signatures/checks
- Optional inactivity lock
- More advanced multi-user authentication

These are not Version 1 requirements.

---

# Security Principles

Priority order:

1. Preserve business data.
2. Prevent unsafe application access.
3. Avoid accidental disclosure.
4. Keep database operations consistent.
5. Keep recovery possible.
6. Keep daily use simple.

Security controls must be described accurately.

In particular, password hashing, file permissions, backup protection, and database encryption are separate concepts and must not be presented as equivalent.
