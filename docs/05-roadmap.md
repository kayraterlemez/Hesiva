# Development Roadmap

## Purpose

This roadmap defines the development order for Hesiva Version 1.

Its purpose is to keep scope under control, prioritize data integrity, and ensure that each milestone remains understandable and testable.

Hesiva will be used for real daily financial tracking. Reliability and simplicity therefore take priority over feature count.

---

# Development Philosophy

The project follows these principles:

- Small, reviewable changes
- Main branch kept working
- Temporary feature branches when useful
- No permanent `develop` or staging branch
- Tests added with business logic
- No unrelated feature work inside focused tasks
- Documentation updated when a decision changes
- No new Version 1 features after V1 scope freeze

A phase is complete when its required behavior is implemented, tested, integrated, and consistent with the project documentation.

---

# Phase 0 — Project Initialization

Goal:

Create a clean project foundation.

Tasks:

- Confirm repository structure
- Configure Python project metadata
- Configure PySide6
- Configure SQLAlchemy and SQLite
- Configure Alembic
- Configure Ruff formatting and linting
- Configure pytest
- Configure `.gitignore`
- Create initial application package
- Create a minimal application entry point
- Add a simple CI check when useful

Do not configure both Black and Ruff Formatter.

Expected result:

The repository installs in a development environment and the application can launch a minimal empty window.

---

# Phase 1 — Core Infrastructure

Goal:

Build the technical foundation.

Tasks:

- Platform-aware application data paths
- Configuration loading/saving
- Logging
- SQLite engine/session management
- Initial Alembic migration
- Password creation
- Argon2id verification
- Login window
- Interrupted first-run resume and conservative populated-database authentication gate
- Password change
- Main application composition
- Main window shell
- Central exception handling

Expected result:

The application starts, initializes its data safely, authenticates the user, and opens the main window.

---

# Phase 2 — Customer Management

Goal:

Implement reliable customer management.

Tasks:

- Create customer
- Edit customer
- Archive customer
- Unarchive customer without cascading to animals
- Customer search
- Customer sorting
- Customer filtering
- Customer notes
- Customer contact information
- Last-activity query support
- Customer integration tests

Expected result:

Customer records can be created, found, edited, archived, and unarchived without losing history.

---

# Phase 3 — Financial Transactions

Goal:

Implement the core account ledger.

Tasks:

- Signed integer-kuruş transaction model
- Create debt transaction
- Receive payment
- Correct an incorrect transaction by voiding it and creating a new transaction when required
- Preserve voided transactions as history without modifying them in place
- Automatic balance calculation from active history
- Present negative balances as absolute **Fazla Ödeme** amounts without changing signed storage
- Transaction history
- Free-text descriptions
- Optional notes
- Same-day ordering
- Financial integration tests

Version 1 does not include a product catalog, transaction line items, or description suggestions.

Expected result:

Daily debt and payment tracking is fully functional and mathematically verifiable from transaction history.

---

# Phase 4 — Animal Management

Goal:

Add optional animal association without creating a medical-record system.

Tasks:

- Add animal
- Edit animal
- Archive animal
- Unarchive animal only while its customer is active
- Associate animals with customers
- Store ear tag numbers
- Store optional name/species/notes
- Associate transaction with optional animal
- Prevent cross-customer animal assignment
- Animal integration tests

Expected result:

A customer may have zero or more animals, and financial transactions may optionally reference them safely.

---

# Phase 5 — Reminder System

Goal:

Provide simple payment reminders.

Tasks:

- Create reminder
- Edit reminder
- Mark reminder completed
- Due/overdue status
- Startup due-reminder check
- Customer reminder indicator
- Reminder tests

The Version 1 startup check is implemented as one application-wide overdue/today summary after the
authenticated Main Window is available. It reuses the customer-scoped reminder tab and is not
re-shown by the midnight presentation refresh.

Expected result:

Users can track future payment promises without external tools.

---

# Phase 6 — Reports

Goal:

Provide the reports required for daily use.

Tasks:

- Customer account statement
- Print-ready statement and summaries
- Statement and summary PDF export
- Monthly debt/payment summary
- Annual debt/payment summary
- Net movement summary
- Date filtering
- Report calculation tests

Advanced charts and analytics are outside Version 1.

Expected result:

Users can print customer history and obtain basic period summaries without misleading debt/payment allocation claims.

---

# Phase 7 — Backup and Restore

Goal:

Protect business data.

Tasks:

- Backup destination setup
- Manual backup
- Automatic backup policy
- SQLite Online Backup API or equivalent SQLite-safe snapshot
- Backup archive creation
- Backup verification
- Retention/rotation
- Restore verification
- Safety backup before restore
- Atomic restore/replacement strategy
- Backup and restore integration tests
- Recovery rehearsal

Expected result:

The application can create verified backups and successfully restore them without relying on raw copies of an active SQLite database.

The manual V1 workflow uses verified ZIP archives containing an Online Backup API database
snapshot and performs recoverable pairwise replacement with a pre-restore safety backup. The
critical automatic-backup requirement is also complete: authenticated startup performs a
once-per-run daily check against the controlled local backup directory, creates no more than one
successful normal automatic backup per local date, and retains 30 calendar days without touching
manual or restore-safety archives.

---

# Phase 8 — Legacy Data Import

Goal:

Migrate the existing Veresiye 5 history.

Tasks:

- Parse and strictly validate the supported framed Veresiye 5 `.exa` profile
- Support validated legacy `.edb` SQLite sources
- Recover only `Frm1.edb` into a private temporary directory and read it strictly read-only
- Decode the discovered legacy text profile as Windows-1254/CP1254
- Read `CariKart` customers
- Read `Data` financial movements
- Count and skip only defined empty customer placeholders and zero-movement `Data` rows
- Preserve useful `legacy_id` references
- Map legacy debt/credit to signed integer-kuruş transactions
- Preserve dates, descriptions, customer relationships, and available times
- Recalculate balances
- Reconcile eligible counts and global/per-customer debt, payment, and net totals
- Generate import report
- Write and verify the destination in one transaction; roll back on critical failure
- Prevent accidental import into a non-empty Version 1 business database
- Perform migration rehearsal before production migration

Expected result:

The old business history can be migrated and reconciled before the legacy application is retired.

---

# Phase 9 — Stabilization

Goal:

Prepare Version 1 for real daily use.

Tasks:

- Fix bugs
- Run complete automated test suite
- Perform manual acceptance workflow
- Test on representative old hardware
- Verify 1366×768 usability
- Verify database integrity
- Verify backup/restore
- Verify migration
- Verify reports
- Verify the minimal Settings and About flows
- Verify the preferred manual-backup destination and authoritative version display
- Build the repeatable Linux x86_64 PyInstaller `onedir` candidate
- Run the frozen-runtime smoke suite with isolated user-data directories
- Rebuild on a release-compatible older glibc baseline and test representative hardware
- Build and validate Windows separately on a clean Windows x86_64 system
- Review logs for sensitive data
- Remove unused/debug code
- Update documentation

No new Version 1 features are introduced during this phase.

Settings remains limited to password change, preferred manual-backup location, and application
version. MIT licensing and the individual copyright holder are now established for release
preparation; a separate build identifier remains outside Version 1.

The packaging foundation produces a locally exercised Linux `onedir` candidate at version 0.1.0.
It does not promote the project to Version 1.0 or establish final release readiness. The
authoritative icon, desktop metadata, Debian package name, maintainer, and license are now defined;
the current host still requires Debian tooling and an older-glibc release build environment before
the `.deb` can be treated as a validated release artifact.

Expected result:

A stable production candidate suitable for side-by-side comparison with the legacy system.

---

# Phase 10 — Production Transition

Goal:

Replace the legacy application safely.

Tasks:

- Create final legacy backup
- Create production migration rehearsal copy
- Import legacy data
- Reconcile aggregate totals
- Compare representative customers side by side
- Create first verified Hesiva backup
- Keep legacy application/data available read-only during transition
- Begin daily use
- Record and fix only blocking/serious issues before declaring Version 1 stable

Expected result:

Hesiva becomes the primary daily application without losing historical records.

---

# Version Plan

## Version 0.1

Project foundation and minimal application launch.

## Version 0.2

Database, configuration, authentication, and main window shell.

Authentication uses the application-data `config.json`, gates the Main Window, resumes incomplete
setup after login, and includes password change without a Version 1 reset/recovery mechanism.

## Version 0.3

Customer management.

## Version 0.4

Financial ledger and payments.

## Version 0.5

Animal management.

## Version 0.6

Reminder system.

## Version 0.7

Reports and PDF/printing.

## Version 0.8

Backup and restore.

## Version 0.9

Legacy Veresiye 5 migration and reconciliation.

## Version 1.0

First stable production release after stabilization and production-transition checks.

---

# Future Versions

## Version 1.5

Possible improvements:

- Recently used description suggestions
- Better filtering
- Saved filters
- Additional reports
- UI refinements
- Performance improvements

These are not Version 1 requirements.

---

## Version 2.0

Potential features only if a real need exists:

- Optional product catalog
- Advanced statistics
- Additional analytics
- Inventory/stock tracking
- Additional import formats
- Optional multi-user/network operation

No Version 2 feature should influence Version 1 implementation without an explicit architecture review.

---

# Roadmap Principles

Development priority is:

1. Data integrity
2. Reliability
3. Simplicity
4. Maintainability
5. User productivity
6. Performance
7. Additional features

A smaller application that reliably replaces the legacy workflow is preferable to a larger application with unnecessary complexity.
