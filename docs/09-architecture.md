# Application Architecture

## Purpose

This document defines the technical architecture of the Cari application.

The architecture exists to keep the application understandable, reliable, testable, and maintainable over many years of use.

Cari is a local-first desktop business application. It is not a distributed system, web application, cloud service, or enterprise ERP platform.

The architecture should therefore remain intentionally simple.

The primary architectural goals are:

- Protect data integrity
- Keep business logic independent from the graphical interface
- Keep database code isolated
- Make individual parts testable
- Make future maintenance predictable
- Avoid unnecessary abstractions
- Allow the application to remain stable for many years

---

# Core Architecture

Cari uses a layered architecture.

The primary dependency flow is:

UI

↓

Services

↓

Repositories

↓

Database

Supporting components such as authentication, backup, importing, reporting, and configuration integrate with these layers without bypassing their responsibilities.

The user interface must never access SQLite directly.

Business rules must never be implemented inside SQL queries or graphical widgets unless the rule is purely related to presentation.

---

# Architectural Principles

## ARCH-001 — Simplicity

The architecture should contain only abstractions that solve real problems.

Patterns must not be introduced only because they are commonly used in large software projects.

Cari is expected to remain a relatively small desktop application.

Simple and readable code is preferred over theoretically perfect but complicated architecture.

---

## ARCH-002 — Dependency Direction

Dependencies flow downward.

UI may depend on Services.

Services may depend on Repositories.

Repositories may depend on the Database layer.

Lower layers must never depend on the UI.

For example:

Correct:

MainWindow
→ CustomerService
→ CustomerRepository
→ SQLite

Incorrect:

CustomerRepository
→ MainWindow

---

## ARCH-003 — UI Isolation

The UI layer is responsible only for:

- Displaying information
- Collecting user input
- Handling keyboard and mouse interaction
- Displaying validation errors
- Displaying application errors
- Updating visible state

The UI must not:

- Execute SQL
- Calculate financial balances
- Perform backup operations directly
- Parse legacy databases
- Hash passwords
- Implement financial business rules

---

## ARCH-004 — Service Layer

Services implement application behavior and business rules.

Examples include:

- Creating customers
- Editing customers
- Creating transactions
- Receiving payments
- Calculating balances
- Creating reminders
- Producing reports
- Coordinating imports
- Coordinating backups

The service layer acts as the main interface between the UI and the rest of the application.

---

## ARCH-005 — Repository Layer

Repositories contain persistence operations.

Examples:

- Find customer by ID
- Search customers
- Insert transaction
- Retrieve transaction history
- Retrieve reminders
- Save animal
- Retrieve yearly financial totals

SQL and ORM-specific database operations must remain inside the repository and database layers.

---

## ARCH-006 — Database Independence

Application behavior should not depend directly on SQLite implementation details whenever this can be avoided without introducing unnecessary complexity.

SQLite is the official Version 1 database and there is currently no requirement to support another database engine.

The abstraction exists for maintainability and testing, not because database replacement is planned.

---

# Technology Stack

Version 1 uses the following primary technologies:

- Python 3.13 or newer
- PySide6
- SQLite
- SQLAlchemy
- Alembic
- Argon2id password hashing
- pytest
- Ruff
- PyInstaller or an equivalent packaging solution

Linux is the primary supported platform.

Windows is a secondary supported platform.

---

# Project Structure

The source tree should approximately follow this structure:

```text
cari/
├── docs/
│
├── src/
│   └── cari/
│       ├── __init__.py
│       ├── __main__.py
│       ├── application.py
│       │
│       ├── models/
│       │   ├── customer.py
│       │   ├── animal.py
│       │   ├── transaction.py
│       │   └── reminder.py
│       │
│       ├── database/
│       │   ├── engine.py
│       │   ├── session.py
│       │   └── migrations/
│       │
│       ├── repositories/
│       │   ├── customer_repository.py
│       │   ├── animal_repository.py
│       │   ├── transaction_repository.py
│       │   └── reminder_repository.py
│       │
│       ├── services/
│       │   ├── customer_service.py
│       │   ├── animal_service.py
│       │   ├── transaction_service.py
│       │   ├── reminder_service.py
│       │   └── report_service.py
│       │
│       ├── ui/
│       │   ├── main_window.py
│       │   ├── dialogs/
│       │   │   ├── login_dialog.py
│       │   │   ├── customer_dialog.py
│       │   │   ├── transaction_dialog.py
│       │   │   ├── payment_dialog.py
│       │   │   ├── animal_dialog.py
│       │   │   └── reminder_dialog.py
│       │   └── widgets/
│       │
│       ├── auth/
│       │   └── auth_service.py
│       │
│       ├── backup/
│       │   └── backup_service.py
│       │
│       ├── importers/
│       │   ├── import_service.py
│       │   └── veresiye5_reader.py
│       │
│       ├── reports/
│       │
│       ├── config/
│       │
│       └── utils/
│
├── tests/
│
├── scripts/
│
├── assets/
│
├── pyproject.toml
├── README.md
└── LICENSE
```

This structure is a guideline rather than an absolute rule.

New directories should only be created when they represent a real responsibility.

---

# Application Startup

Application startup follows this general sequence:

```text
Application starts
        ↓
Locate application data directory
        ↓
Load configuration
        ↓
Initialize logging
        ↓
Check first-run state
        ↓
Initialize database engine
        ↓
If schema migration is required:
    create recovery backup
    run migration
        ↓
Initialize repositories
        ↓
Initialize services
        ↓
First-run password setup or authentication
        ↓
Check due reminders
        ↓
Open main window
```

Exact first-run ordering may differ slightly because a brand-new database has no existing data to back up.

Significant migrations of an existing database require an appropriate recovery point before schema changes.

# Application Composition

Object creation should occur in one central location.

This is sometimes called the composition root.

`application.py` is responsible for creating and connecting the major components.

Conceptually:

```text
Database
    ↓
Repositories
    ↓
Services
    ↓
Main Window
```

For example:

```text
CustomerRepository
        ↓
CustomerService
        ↓
MainWindow
```

Individual UI widgets should not construct their own database connections or repositories.

---

# Domain Models

The primary Version 1 domain entities are:

- Customer
- Animal
- Transaction
- Reminder

A Customer represents the person or business whose account is being tracked.

An Animal optionally belongs to a Customer.

A Transaction represents a financial movement associated with a Customer.

A Reminder represents a future action associated with a Customer.

The authoritative Version 1 model fields are:

```text
Customer
- id
- legacy_id (nullable)
- registered_on (nullable)
- full_name
- phone (nullable)
- address (nullable)
- notes (nullable)
- created_at
- updated_at
- archived_at (nullable)

Animal
- id
- customer_id
- ear_tag (nullable)
- name (nullable)
- species (nullable)
- notes (nullable)
- created_at
- updated_at
- archived_at (nullable)

Transaction
- id
- customer_id
- animal_id (nullable)
- legacy_id (nullable)
- transaction_date
- transaction_time (nullable)
- description
- amount_kurus
- note (nullable)
- created_at
- updated_at
- voided_at (nullable)
- void_reason (nullable)

Reminder
- id
- customer_id
- remind_on
- note
- created_at
- updated_at
- completed_at (nullable)
- cancelled_at (nullable)
```

`registered_on` is business/history data and is distinct from `created_at`, which records when the Cari row itself was created.

Customers and animals use nullable archive timestamps rather than Boolean archive flags. Reminders use completion/cancellation timestamps rather than a Boolean status so the application preserves when those events occurred.

Version 1 intentionally does not contain:

- TransactionItem entities
- CatalogItem entities
- Inventory entities
- Medical record entities
- Product stock entities
- Supplier entities

These may be introduced in future versions only if required.

---

# Transaction Model

Version 1 uses a deliberately simple ledger model.

One `Transaction` represents one financial movement.

A transaction contains:

- Customer
- Optional animal
- Business date
- Optional transaction time
- Free-text description
- Signed integer amount in kuruş
- Optional note
- Technical creation/update metadata
- Optional legacy reference
- Optional void metadata

There is no `TransactionItem` or product/catalog entity in Version 1.

Financial direction is represented by the sign of `amount_kurus`:

```text
amount_kurus > 0  → debt/charge
amount_kurus < 0  → payment/credit
amount_kurus == 0 → invalid
```

Example:

```text
Birth + Medicine       +1500 TL
Treatment               +500 TL
Payment                 -500 TL
```

Outstanding balance:

```text
1500 TL
```

Payments are not associated with individual debt records.

A negative final balance is allowed and represents customer credit.

Incorrect financial movements are voided rather than physically deleted.

# Balance Calculation

Customer balance is never an authoritative stored customer value.

The source of truth is the set of non-voided financial transactions.

Conceptually:

```text
balance_kurus = SUM(amount_kurus)
```

Positive movements increase outstanding debt.

Negative movements reduce outstanding debt.

Voided movements are excluded.

Summary values may be calculated efficiently through SQL aggregation, but every displayed balance must remain reproducible from transaction history.

# Monetary Values

Floating-point numbers must never be used for stored financial values.

Version 1 should store monetary values as integer minor units.

For Turkish Lira:

```text
1 TL = 100 kuruş
```

Example:

```text
1500.00 TL
```

is stored internally as:

```text
150000
```

This avoids floating-point rounding errors.

Formatting into Turkish Lira is performed only for display.

---

# Customer Flow

Creating a customer follows this path:

```text
Customer Dialog
        ↓
Customer Service
        ↓
Validation
        ↓
Customer Repository
        ↓
SQLite
```

The UI collects information.

The service validates business rules.

The repository stores the record.

The UI is notified of success or failure.

---

# Transaction Flow

Creating a transaction follows this path:

```text
New Transaction Dialog
        ↓
Transaction Service
        ↓
Validate input
        ↓
Begin database transaction
        ↓
Transaction Repository
        ↓
Commit
        ↓
Refresh customer balance and history
```

The database operation must be atomic.

If any part fails, the operation is rolled back.

A partially created transaction must never remain in the database.

---

# Payment Flow

The payment dialog accepts a normal positive amount from the user.

The service layer converts that value to a negative signed financial movement exactly once.

```text
Payment Dialog
        ↓
Transaction Service
        ↓
Validate positive UI amount
        ↓
Convert to negative amount_kurus
        ↓
Transaction Repository
        ↓
Commit
        ↓
Refresh balance/history from persisted data
```

The UI must not manually subtract the payment from the visible balance.

The displayed balance is refreshed from application data after the payment has been successfully committed.

Payments larger than the current positive balance are valid; the resulting negative balance represents customer credit.

# Animal Flow

Animals are optional.

Creating an animal follows:

```text
Animal Dialog
        ↓
Animal Service
        ↓
Animal Repository
        ↓
SQLite
```

Transactions may optionally reference an animal.

Deleting or archiving an animal must never delete associated financial history.

---

# Reminder Architecture

Reminder processing is handled by `ReminderService`.

At startup:

```text
Application starts
        ↓
ReminderService
        ↓
Retrieve due reminders
        ↓
Main Window
        ↓
Display notification state
```

A reminder contains:

- Customer
- Reminder date
- Description
- Completion state

The reminder system must not require an Internet connection.

Desktop notifications may be added, but reminders must remain visible inside the application even if operating-system notifications are unavailable.

---

# Authentication Architecture

Authentication is handled separately from the UI.

```text
Login Dialog
        ↓
AuthService
        ↓
Argon2id verification
        ↓
Success / Failure
```

The UI never performs password hashing itself.

Passwords are never stored in plain text.

Only password hashes are stored.

Authentication in Version 1 is application-level protection.

It prevents casual unauthorized access through the application.

It does not encrypt the SQLite database itself.

Database file access is additionally protected using operating-system file permissions.

Full database-at-rest encryption may be evaluated in a future version if required.

---

# Backup Architecture

Backup operations are handled by `BackupService`.

The UI only requests a backup operation.

```text
UI
 ↓
BackupService
 ↓
SQLite backup operation
 ↓
Verification
 ↓
Backup archive
 ↓
Destination
```

The application must not create backups by blindly copying an active SQLite database file.

SQLite may use additional journal or WAL files.

Backups should therefore use a SQLite-safe backup mechanism such as the SQLite Online Backup API.

After the database snapshot is created, backup metadata and configuration may be added to the final archive.

The resulting backup must be verified before being reported as successful.

---

# Restore Architecture

Restore follows a defensive process.

```text
User selects backup
        ↓
Verify backup
        ↓
Create safety backup of current database
        ↓
Close active database sessions
        ↓
Restore selected database
        ↓
Verify restored database
        ↓
Restart or reinitialize application
```

A failed restore must not destroy the currently working database.

---

# Legacy Import Architecture

Legacy import is isolated from the normal database layer.

The old database must always be opened read-only.

Conceptually:

```text
Legacy Source
      ↓
Veresiye5Reader
      ↓
Validation
      ↓
Mapping
      ↓
ImportService
      ↓
Current Repositories
      ↓
Current SQLite Database
```

`Veresiye5Reader` understands the legacy database structure.

The rest of the application should not know legacy table names such as `CariKart` or `Data`.

This isolates legacy-specific code in one location.

---

# Legacy Mapping

Legacy-specific knowledge remains isolated inside the Veresiye 5 importer.

Known conceptual mapping:

```text
CariKart
    ↓
Customer

Data
    ↓
Transaction
```

Important mappings include:

```text
CariKart.ID        → Customer.legacy_id
CariKart.Unvan     → Customer.full_name
Data.ID            → Transaction.legacy_id
Data.CariKartID    → customer relationship through explicit ID mapping
Data.Tarih         → Transaction.transaction_date
Data.Saat          → Transaction.transaction_time when valid
Data.Aciklama      → Transaction.description
Data.Borc          → positive amount_kurus
Data.Alacak        → negative amount_kurus
```

Legacy summary values such as `Borc`, `Alacak`, `Bakiye`, and `STarih` are not authoritative current fields.

They may be used for reconciliation.

Legacy identifiers are optional reference metadata only and never become current primary keys.

# Import Transactions

Version 1 legacy migration is intended for an empty Cari business database.

This intentionally avoids unsafe merge semantics during the first production migration.

The destination write should be atomic whenever practical:

```text
Validate source read-only
        ↓
Validate empty destination
        ↓
Begin destination transaction
        ↓
Create customers
        ↓
Map legacy customer IDs to current IDs
        ↓
Create financial movements
        ↓
Reconcile counts/totals/relationships
        ↓
Commit
```

If a critical error occurs:

```text
Rollback
```

Partial production migration must not silently remain.

If implementation constraints make a single transaction impractical, an isolated staging database may be built and verified before being promoted to the production location.

# Reports Architecture

Reports are generated through `ReportService`.

The UI does not independently calculate report values.

```text
Reports UI
    ↓
ReportService
    ↓
Repositories
    ↓
Aggregated transaction data
    ↓
PDF / Print output
```

Version 1 reports include:

- Customer account statements
- Monthly debt totals
- Monthly payment totals
- Annual debt totals
- Annual payment totals
- Net movement summaries
- Outstanding balances where appropriate

Period totals are filtered by transaction business date and exclude voided transactions.

Because Version 1 does not allocate payments to individual debts, reports must not claim that payments received in a period necessarily paid debts created in that period.

# Configuration

Application configuration is logically separate from business records.

Configuration may contain:

- Password hash
- Backup destination
- Window state
- UI preferences
- Application preferences

Version 1 does not require inactivity-lock settings because the authenticated session remains unlocked until the application closes.

Configuration may be stored in a platform-appropriate file such as `config.json`, using safe/atomic writes where appropriate.

Platform-specific application directories must be used instead of the installation directory.

Examples:

Linux:

```text
~/.local/share/cari/
```

Windows:

```text
%LOCALAPPDATA%\Cari\
```

Exact paths should be resolved through a cross-platform helper rather than hard-coded.

# Database Location

The production database must not be stored inside:

- Source directory
- Installation directory
- Temporary directory
- Downloads directory

The database belongs inside the application's persistent user data directory.

The development environment may use separate test databases.

---

# Database Migrations

Database schema changes are managed using migrations.

Alembic is used for schema versioning.

Example:

```text
Version 1.0 database
        ↓
Application update
        ↓
Backup
        ↓
Migration
        ↓
Version 1.1 database
```

Every migration must be designed to preserve existing user data.

A backup must be created before destructive or significant migrations.

---

# Threading

Normal database operations are expected to be fast enough to run synchronously.

Long-running operations should not freeze the UI.

Potential background operations include:

- Legacy import
- Large backup creation
- Large restore operations
- Complex report generation

PySide6 worker threads may be used for these tasks.

SQLite sessions or connections must not be unsafely shared between threads.

Each worker should use an appropriate independent database session.

---

# Error Handling

Errors are separated into layers.

Repository errors represent persistence failures.

Service errors represent application or business failures.

UI errors represent messages displayed to the user.

Conceptually:

```text
SQLite Error
    ↓
Repository
    ↓
Application Error
    ↓
Service
    ↓
User-friendly message
```

Raw SQL errors should not normally be displayed directly to the user.

---

# Logging

Logging exists for troubleshooting and diagnostics.

Logs may include:

- Application startup
- Application shutdown
- Migration results
- Backup results
- Import results
- Unexpected exceptions

Logs must not contain:

- Passwords
- Password hashes
- Complete customer records
- Sensitive customer notes
- Complete financial histories

Log files should remain small and automatically rotated if necessary.

---

# Data Integrity

Data integrity has higher priority than performance.

All write operations should use database transactions.

Foreign key constraints should be enabled.

Database integrity should be checked when appropriate.

Historical transactions should never be silently changed.

Operations that may significantly modify data should create recovery points when practical.

---

# Deletion Policy

Financial history should not normally be physically deleted.

Records that should disappear from normal use may be archived or marked inactive.

Examples:

- Customer archived
- Animal archived
- Incorrect transaction voided

Permanent deletion should only be considered when there is a specific and documented reason.

Deleting a parent object must never accidentally cascade-delete important financial history.

---

# Testing Architecture

Tests should be able to use temporary SQLite databases.

Production user data must never be used during automated tests.

Services and repositories should be testable independently from the graphical interface.

Important business rules should be tested without launching PySide6 whenever possible.

Examples:

- Balance calculation
- Payment behavior
- Customer creation
- Reminder retrieval
- Import mapping
- Backup verification

---

# Packaging

The application should be distributable without requiring the user to configure a Python development environment.

Linux is the primary packaging target.

Windows packages may be generated separately.

Application data must remain separate from application binaries so that reinstalling or updating the application does not delete user records.

---

# Version 1 Boundaries

Version 1 deliberately does not include:

- Cloud synchronization
- Server infrastructure
- Multi-user networking
- Inventory management
- Medical record management
- Mobile application
- Web application
- Plugin architecture

These features must not influence Version 1 architecture unless there is a concrete future requirement.

---

# Future Expansion

The architecture should allow future modules to be introduced without rewriting the core application.

Possible future additions include:

- Product catalog
- Advanced analytics
- Inventory
- Additional import formats
- Multi-user operation
- Network synchronization

Future flexibility must not justify unnecessary complexity in Version 1.

---

# Summary

Cari uses a simple layered architecture:

```text
PySide6 UI
    ↓
Services
    ↓
Repositories
    ↓
SQLAlchemy
    ↓
SQLite
```

Additional systems such as authentication, imports, backups, reminders, and reports remain isolated behind dedicated services.

The architecture prioritizes:

1. Data integrity
2. Reliability
3. Simplicity
4. Maintainability
5. Testability
6. Performance

The application should remain understandable enough that a developer can return to the project years later, read the architecture documentation, and understand where each responsibility belongs.

The architecture is considered successful if it makes incorrect code difficult to write while keeping correct code simple to understand.
