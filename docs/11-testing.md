# Testing Strategy

## Purpose

This document defines the testing strategy for the Hesiva application.

Hesiva stores long-term customer and financial data.

A defect in a normal desktop application may be inconvenient.

A defect in Hesiva may:

- Display an incorrect customer balance
- Lose a financial transaction
- Import historical data incorrectly
- Create an unusable backup
- Damage data during a migration
- Associate a transaction with the wrong customer
- Misreport yearly financial totals

For this reason, testing is considered part of implementation rather than a separate activity performed only before release.

The purpose of testing is not to maximize the number of tests.

The purpose is to provide confidence that important application behavior remains correct as the software changes.

---

# Testing Priorities

Testing priorities follow the risk of the application.

The highest-priority areas are:

1. Financial calculations
2. Database integrity
3. Transaction creation and void-based correction
4. Backup and restore
5. Legacy data import
6. Database migrations
7. Customer relationships
8. Authentication
9. Reminder behavior
10. Reports
11. User interface behavior

Visual details are important, but financial correctness and data preservation have higher priority.

---

# Testing Philosophy

Tests should verify observable behavior.

Tests should not unnecessarily depend on private implementation details.

A test should answer questions such as:

```text
If a customer has 1500 TL debt and pays 300 TL,
is the resulting balance 1200 TL?
```

rather than:

```text
Was private method _calculate_internal_value() called twice?
```

Implementation may change.

Business behavior should remain stable.

---

# Test Types

Hesiva uses several levels of testing.

```text
Unit Tests
    ↓
Integration Tests
    ↓
UI Tests
    ↓
Manual Acceptance Tests
```

Not every feature requires every test type.

The appropriate level depends on risk.

---

# Unit Tests

Unit tests verify small pieces of application logic without requiring the complete application.

Examples include:

- Money parsing
- Money formatting
- Balance rules
- Date parsing
- Validation functions
- Reminder due-date logic
- Legacy field conversion
- Search normalization

Unit tests should normally be:

- Fast
- Deterministic
- Independent
- Easy to understand

Example:

```python
def test_parse_lira_converts_decimal_text_to_kurus() -> None:
    assert parse_lira("1500,50") == 150050
```

Unit tests should not require the production database.

---

# Integration Tests

Integration tests verify that multiple application components work together correctly.

Examples:

```text
Service
↓
Repository
↓
SQLAlchemy
↓
Temporary SQLite Database
```

Integration tests are especially important for Hesiva because many critical behaviors involve database state.

Examples include:

- Creating a customer
- Creating a debt transaction
- Creating a payment
- Calculating a balance from stored transactions
- Associating an animal with a customer
- Retrieving reminders
- Voiding a transaction
- Running a migration
- Importing legacy data

Integration tests should use real SQLite databases created specifically for the test.

Mocks should not replace SQLite when the behavior being tested depends on SQLite.

---

# UI Tests

Automated UI testing should be selective.

The entire application does not need to be tested through simulated mouse clicks.

Business rules should normally be tested below the UI layer.

Automated PySide6 tests are useful for critical interface behavior such as:

- Dialog opens successfully
- Required fields are present
- Save action calls the expected service
- Validation errors are displayed
- Keyboard shortcuts behave correctly
- Dialog closes after successful save
- Dialog remains open after failed save

`pytest-qt` may be introduced if automated Qt testing becomes valuable.

It should only be added if it provides a clear benefit.

---

# Manual Testing

Manual testing remains necessary for desktop usability.

Some behavior is easier and more meaningful to verify manually.

Examples:

- Window layout at 1366x768
- Text readability
- Keyboard navigation
- Tab order
- Search responsiveness
- Dialog sizing
- Printing
- PDF appearance
- Linux desktop behavior
- Windows behavior
- Backup destination selection
- External USB backup usage

Manual tests complement automated tests.

They do not replace automated tests for business-critical logic.

---

# Test Directory Structure

Tests should approximately follow the application structure.

Example:

```text
tests/
├── unit/
│   ├── test_money.py
│   ├── test_dates.py
│   ├── test_validation.py
│   └── test_reminders.py
│
├── integration/
│   ├── test_customers.py
│   ├── test_transactions.py
│   ├── test_animals.py
│   ├── test_reminders.py
│   ├── test_import.py
│   ├── test_backup.py
│   └── test_migrations.py
│
├── ui/
│   ├── test_customer_dialog.py
│   └── test_transaction_dialog.py
│
├── fixtures/
│
└── conftest.py
```

The exact structure may evolve as the application grows.

Directories should not be created before they are useful.

---

# Test Database

Automated tests must never use the real Hesiva production database.

Every database test must use a temporary database.

Example:

```text
Temporary Directory
        ↓
test.db
        ↓
Run test
        ↓
Delete temporary directory
```

Tests must not depend on:

```text
~/.local/share/hesiva/
```

or:

```text
%LOCALAPPDATA%\Hesiva\
```

Temporary paths should be supplied explicitly.

---

# Test Isolation

Tests must not depend on execution order.

Incorrect:

```text
test_01_create_customer
test_02_use_customer_created_by_test_01
test_03_delete_customer
```

Correct:

Each test creates the state it needs.

A test should produce the same result whether it runs:

- Alone
- Before another test
- After another test
- As part of the complete suite

---

# Test Data

Tests must use synthetic data.

Real customer information must never be copied into the repository.

Do not commit:

- Real names
- Real phone numbers
- Real addresses
- Real financial records
- Real customer notes
- Complete legacy customer databases

Example synthetic data:

```text
Customer: Test Customer 1
Phone: 05000000001
Description: Test Treatment
Amount: 1500.00 TL
```

Legacy import fixtures should also be synthetic or properly anonymized.

---

# Financial Tests

Financial behavior has the highest testing priority.

Every important financial rule should have automated coverage.

---

# Basic Debt Test

Example:

```text
Customer created

Debt:
1500 TL
```

Expected balance:

```text
1500 TL
```

---

# Basic Payment Test

Example:

```text
Debt:
1500 TL

Payment:
300 TL
```

Expected balance:

```text
1200 TL
```

---

# Multiple Transactions

Example:

```text
Birth              +500 TL
Medicine           +400 TL
Treatment          +600 TL
Payment            -500 TL
```

Expected balance:

```text
1000 TL
```

The application must not require the payment to be associated with a specific debt transaction.

---

# Full Payment

Example:

```text
Debt:
750 TL

Payment:
750 TL
```

Expected balance:

```text
0 TL
```

---

# Overpayment

Version 1 allows a negative customer balance.

Example:

```text
Debt:
500 TL

Payment:
700 TL
```

Expected balance:

```text
-200 TL
```

The negative internal balance represents customer credit. The UI presents it without the minus sign
as **200 TL Fazla Ödeme**. Positive balances use **Borç**, and zero is neutral.

Tests must verify that overpayment is not silently clamped to zero, that reports/search/sorting
handle negative balances consistently, and that presentation does not mutate the signed value.

# Zero Amount

Transactions with a zero financial amount should normally be rejected.

Example:

```text
Amount:
0 TL
```

Expected:

```text
Validation error
```

---

# Negative User Input

The normal debt and payment dialogs should not require users to manually enter signed values.

For a normal payment:

```text
User enters:
300 TL
```

The service stores:

```text
-30000 kuruş
```

The sign of `amount_kurus` is the authoritative financial direction.

Tests must verify that sign conversion occurs exactly once and cannot accidentally turn a payment back into a positive debt.

Zero is invalid.

# Money Precision

Financial tests must verify exact kuruş behavior.

Examples:

```text
0.01 TL
1.99 TL
10.10 TL
1500.00 TL
1500.50 TL
```

Expected internal representations:

```text
1
199
1010
150000
150050
```

No financial test should use approximate floating-point comparisons for authoritative amounts.

---

# Money Input Parsing

The application should test accepted user input formats.

Examples may include:

```text
1500
1500,5
1500,50
1500.50
```

The exact accepted formats must be defined by implementation requirements.

Ambiguous or invalid input must be rejected rather than silently interpreted incorrectly.

Examples of invalid input may include:

```text
abc
15x20
--
```

---

# Balance Recalculation

Balance must always be reproducible from transaction history.

A test should create multiple transactions and independently verify that querying the customer balance produces the expected result.

There should be no dependency on a manually updated stored balance column.

---

# Transaction Void

Incorrect financial movements are voided rather than physically deleted.

Example:

```text
Debt A:
500 TL

Debt B:
300 TL
```

Balance:

```text
800 TL
```

Void Debt B.

Expected active balance:

```text
500 TL
```

The voided record remains stored for historical/reference purposes.

Tests must also verify that a voided transaction is excluded from:

- Active balance
- Last activity calculation
- Normal monthly/yearly financial summaries

while remaining retrievable when historical/voided records are intentionally requested.

# Transaction Correction

Version 1 does not directly edit an existing financial transaction. Correction voids the incorrect
transaction and creates a separate correct transaction when required.

Tests must verify that correction:

- Preserves the voided transaction as historical data.
- Excludes the voided amount from active balance and normal reports.
- Creates the corrected entry as a new transaction with its own identity.
- Does not silently change the original transaction's business fields.
- Allows the void reason to remain absent.
- Does not affect another customer.

Version 1 does not require correction-lineage fields or audit tables linking the two records.

---

# Customer Tests

Customer tests should include:

- Create customer
- Read customer
- Update customer
- Archive customer
- Unarchive customer
- Search customer
- Customer with optional fields missing
- Multiple customers with identical names
- Customer `registered_on` business date
- Customer `created_at` metadata timestamp
- Nullable `archived_at` behavior
- Legacy identifier behavior

A customer should not require a unique human name.

Two customers may legitimately have the same name.

---

# Customer Archiving

Archiving a customer must not delete:

- Transactions
- Animals
- Reminders
- Historical information

Tests should verify that `archived_at IS NULL` represents an active customer, setting `archived_at`
archives the customer without deleting history, and unarchiving restores NULL idempotently. Customer
unarchive must not change child animal archive states. Archived customers must remain accessible to
the explicit unarchive workflow while their history remains intact.

---

# Animal Tests

Animal tests should include:

- Create animal for customer
- Retrieve customer's animals
- Update animal
- Archive animal using `archived_at`
- Unarchive animal using `archived_at`
- Optional ear tag
- Optional animal name
- Transaction without animal
- Transaction with animal

Most importantly:

> A transaction must not be associated with an animal owned by another customer.

This rule requires an automated test.

Tests must also verify that animal unarchive is idempotent for an active owner and is rejected while
the owning customer remains archived. Rejection must leave both archive states unchanged and must
not implicitly unarchive the customer.

Example:

```text
Customer A
    Animal A

Customer B
```

Attempt:

```text
Create transaction for Customer B
using Animal A
```

Expected:

```text
Rejected
```

---

# Reminder Tests

Reminder tests should include:

- Reminder in the future
- Reminder due today
- Reminder in the past
- Completed reminder using `completed_at`
- Cancelled reminder using `cancelled_at`
- Active reminder with both timestamps NULL
- Multiple reminders for one customer
- Reminder retrieval during startup
- Application-wide overdue/today counts across customers in one bounded query
- No startup summary for zero due reminders and at most one summary per application run
- Safe-default summary dismissal and deterministic navigation to the existing reminder tab
- Completed, cancelled, and future reminder exclusion, including local-date boundary behavior

A reminder is active only while both `completed_at` and `cancelled_at` are NULL. A completed or cancelled reminder should not continue to appear as an active due reminder.

Date boundary behavior should be tested explicitly.

Automatic-backup tests use injected local datetimes and verify first-day creation, same-day skip,
next-day creation, independent archive validation, controlled destination selection, and no retry
after failure. Retention tests cover the 30-calendar-day boundary, corrupt lookalikes, symlinks,
renamed/manual metadata mismatches, hard-linked ambiguity, manual/safety/unrelated preservation,
cleanup failure after a successful backup, and the rule that cleanup never runs merely because a
valid backup already existed for the day.

---

# Domain Model Schema Tests

The initial ORM/migration milestone should explicitly verify the authoritative Version 1 field semantics.

At minimum:

- `Customer.registered_on` is nullable and independent from `created_at`.
- `Customer.archived_at` is nullable.
- `Animal.archived_at` is nullable.
- `Transaction.transaction_time` is nullable so legacy `Data.Saat` can be preserved when valid.
- `Transaction.amount_kurus` rejects zero and accepts positive and negative integers.
- `Reminder.completed_at` and `Reminder.cancelled_at` are nullable.
- Reminder completion/cancellation does not physically delete the reminder.
- `legacy_id` is nullable for customers and transactions.

These tests protect the schema from drifting back toward earlier Boolean archive/completion designs.

---

# Authentication Tests

Authentication tests should verify:

- First-run password creation
- Correct password accepted
- Incorrect password rejected
- Password not stored as plain text
- Password hash verifies correctly
- Changed password behavior if supported
- Empty password behavior according to requirements
- Exact `config.json` structure, malformed-state rejection, and unknown-field preservation
- Missing/null/configured backup-destination resolution and cross-platform absolute-path validation
- Locked production Argon2id parameters with a lower-cost injected test hasher where appropriate
- Fresh, incomplete, complete, and blocked startup state transitions
- No Main Window construction before successful authentication
- Import-success/final-config-write recovery without duplicate import
- Atomic credential publication and old-password preservation on failed password change
- Real configuration in backups and pairwise database/configuration restore and rollback
- Exclusive application-data ownership, crashed-owner recovery, and a real hot-journal startup case
- Abrupt restore interruption before/after config publication and deterministic startup recovery
- Backup rejection for triggers/views, foreign-key/ownership faults, non-integer kuruş, invalid
  dates, unsafe financial aggregate ranges, resource-limit violations, and an
  already/race-created destination
- ZIP entry-count and central-directory limits must be enforced before `ZipFile` materializes its
  member list
- Symbolic-link and hard-link aliases of the live database must be rejected before SQLite opens;
  only the exact abandoned fresh-publication hard-link pair may be recovered
- Direct legacy `.edb` hard links must be rejected, including a real WAL case where the selected
  alias has no adjacent sidecar but another link name owns committed WAL data
- Exact signed-integer money boundaries, cumulative same-side overflow rejection, and capacity
  released by voiding a movement
- Fail-closed startup of a pre-existing financially unsafe database, with byte-for-byte
  preservation, validation of individual voided values, and voided-row exclusion from aggregate
  capacity
- Backup temporal-text limits must reject oversized values through SQLite scalar predicates before
  selecting those values into Python for canonical date/time parsing
- Customer, animal, transaction/void, and reminder services must share the same 1 MiB UTF-8 text
  ceiling as backup validation; legacy mapped output must be rejected before import if it exceeds
  that destination ceiling
- Money parsing must reject over-range or pathologically long digit input as a presentation error
  before Python's integer-conversion guard can raise
- Configuration parsing must classify huge JSON integers and non-standard `NaN`/infinity constants
  as invalid configuration

Settings and About tests should additionally verify:

- Backup-location updates preserve all authentication fields and take effect without restart
- Selecting a location neither creates a backup nor moves existing backups
- An unavailable configured destination does not block startup and does not silently fall back
- Settings exposes no password hash, reset path, or fabricated preferences
- About uses the authoritative `pyproject.toml` version in source-tree execution
- About shows the authoritative MIT label and omits independent build, publisher, cloud, and
  encryption claims
- Settings, password change, and About appear once in the final menu flow

Tests must never assert or log real user passwords.

Test passwords should be synthetic.

Alembic tests must also verify that loading the repository logging configuration does not disable
pre-existing Hesiva loggers in the shared application/test process; otherwise later privacy-log
regressions can pass alone while observing no records in the complete suite.

---

# Password Hash Tests

Tests should verify behavior rather than depend on a hard-coded Argon2 hash string.

Because Argon2 uses salts, hashing the same password multiple times may produce different hash strings.

Correct test:

```text
Hash password
↓
Verify password against hash
↓
Success
```

Incorrect assumption:

```text
hash("password") == fixed_string
```

---

# Legacy Import Tests

Legacy import is one of the highest-risk components.

It should receive extensive automated testing.

A synthetic Veresiye 5 source should be created for tests. It must reproduce only the supported
framed EXA structure and exact required EDB schema, use invented data, and exercise the complete
`.exa` → temporary `Frm1.edb` → read-only source → atomic Hesiva import path. Real customer backups
must never be committed as fixtures.

The source database contains exact supported-profile versions of:

```text
CariKart
Data
ATemp
```

Import tests should never require the real business database.

Parser tests cover malformed/truncated framing, invalid `FILE:LIST`, missing/duplicate
`Frm1.edb`, bad `XEC2` markers and flags, corrupt or incomplete zlib records, size mismatches, and
trailing bytes. Source hashes and absence of SQLite sidecars verify read-only behavior.

Synthetic source text includes all Turkish Windows-1254 letters. Tests require strict CP1254
decoding, normal destination Unicode round-trip, and rejection rather than replacement of
undecodable bytes. Dates use exact `YYYY-MM-DD`, nonblank times use exact `HH:MM:SS`, and money tests
cover NULL, INTEGER, REAL, one/two-decimal values, and rejected ambiguous precision/types.

---

# Legacy Customer Import

Test:

```text
Legacy CariKart
ID = 15
Name = Test Customer
```

After import:

```text
Customer exists
legacy_id = 15
```

The current application ID does not need to equal 15.

---

# Legacy Transaction Import

Test legacy movements such as:

```text
Debt:
500 TL

Debt:
300 TL

Payment:
200 TL
```

Expected imported balance:

```text
600 TL
```

All historical movements should remain visible after import.

---

# Import Relationship Mapping

Legacy relationships must remain correct.

Example:

```text
CariKart.ID = 42
```

and:

```text
Data.CariKartID = 42
```

must result in the transaction belonging to the newly created Customer representing legacy customer 42.

The importer must not assume that the new customer ID is also 42.

---

# Import Balance Verification

The importer should compare legacy summary values with the result calculated from imported transaction history when legacy summary values are available.

Example:

```text
Legacy stored balance:
1500 TL

Imported transaction calculated balance:
1500 TL
```

Expected:

```text
Match
```

If:

```text
Legacy:
1500 TL

Calculated:
1450 TL
```

expected behavior should be:

```text
Import warning
```

The transaction history remains authoritative in the new application.

Tests also prove that legacy `STarih` does not determine Son İşlem.

---

# Import Rollback

Import must be tested for failure in the middle of migration.

Example:

```text
100 customers expected

50 imported

Critical error occurs
```

Expected result:

```text
No partial import remains
```

The database should return to the state it had before the failed import operation.

Separate tests force failure after customer flush, during transaction insertion, and during final
verification. Each case must leave no customer, transaction, or preserved legacy ID behind.

---

# Import Source Protection

Tests should verify that import logic opens legacy data read-only wherever practical.

The source database must not be modified by importing.

For automated fixtures, the source file may be hashed or inspected before and after import to verify that it has not changed.

---

# Duplicate Import

Version 1 legacy migration is intended for an empty Hesiva business database.

Tests should verify that:

- A valid legacy migration succeeds into an empty destination.
- A complete legacy migration is rejected when the destination already contains active/imported business data.
- Re-running the same migration cannot silently duplicate all customers and transactions.
- Preserved `legacy_id` values remain available for reconciliation and troubleshooting.

General merge/deduplication behavior for non-empty destinations is outside Version 1.

# Invalid Legacy Data

Synthetic legacy fixtures should include problematic cases such as:

- Missing customer
- Invalid customer reference
- Invalid date
- Empty description
- Invalid amount
- Unexpected NULL
- Unsupported table structure

They also cover the two defined non-blocking translations:

- A structurally empty, unreferenced nameless customer is skipped and counted.
- A row whose normalized `Borc` and `Alacak` are both zero is skipped and counted.

A nameless customer with meaningful data or linked transactions remains blocking. Zero rows must
not create fake one-kuruş transactions or other domain records.

The importer should produce controlled errors or warnings.

It must not crash unpredictably or silently discard important records.

---

# Import Reconciliation

After import, automated reconciliation should verify important totals.

At minimum:

```text
Number of customers
Number of financial movements
Total debt
Total payments
Calculated balances
```

should be compared where the legacy source contains sufficient information.

Counts distinguish source rows, defined skipped rows, and eligible/imported rows. Debt, payment,
and signed net reconcile globally and for every imported customer before commit; stored customer
summaries are reported separately as reconciliation-only values.

This is one of the most important safeguards in the migration process.

---

# Backup Tests

A backup is not considered successful merely because a file exists.

Tests must verify that the backup can actually be used.

Backup tests should include:

- Backup file created
- Snapshot contains valid SQLite database
- Required metadata exists
- Backup verification succeeds
- Invalid backup rejected
- Current database remains unchanged
- Destination failure handled safely
- Existing destination is never overwritten, including publication races
- Interrupted destination writes are not reported as successful and any partial new file fails
  normal backup validation

---

# SQLite Backup Test

The application must use a SQLite-safe backup mechanism.

A test should:

```text
Create database
↓
Insert known records
↓
Create backup
↓
Open backup independently
↓
Read known records
```

Expected:

```text
All records are present and valid
```

---

# Restore Tests

Restore is a high-risk operation.

Tests should include:

- Restore valid backup
- Reject corrupted archive
- Reject missing database
- Preserve safety backup
- Restore known customer records
- Restore transaction history
- Verify balances after restore

A failed restore must not destroy the current working database.

---

# Restore Round Trip

One important integration test is:

```text
Create database A
↓
Add known records
↓
Create backup
↓
Modify database A
↓
Restore backup
↓
Verify original records
```

This validates the complete backup/restore cycle.

---

# Migration Tests

Database migrations must preserve existing records.

A migration test should conceptually:

```text
Create database using old schema
↓
Insert representative data
↓
Run migration
↓
Verify new schema
↓
Verify original data
```

Migrations should never be tested only against empty databases.

Real installations will contain existing customer history.

---

# Migration Failure

Significant migrations should be tested for failure behavior when practical.

The application should not leave a database silently half-migrated.

Backup-before-migration behavior should also be verified where implemented.

---

# Report Tests

Reports contain financial calculations and therefore require automated verification.

Reports should test the data used to generate output separately from PDF appearance.

Examples:

- Annual debt total
- Annual payment total
- Monthly debt total
- Monthly payment total
- Customer statement
- Current balance
- Date filtering

Example:

```text
2025 debt:
10,000 TL

2025 payments:
6,000 TL
```

Expected report values:

```text
Debt created during 2025:
10,000 TL

Payments received during 2025:
6,000 TL
```

Reports must not claim that payments received during the year necessarily paid debts created during the same year unless explicit allocation logic exists.

---

# Date Tests

Date-related behavior should include boundary conditions.

Examples:

- First day of month
- Last day of month
- First day of year
- Last day of year
- Leap year
- Historical dates
- Today's date
- Future reminder date

Tests should not depend unnecessarily on the actual date when the test suite happens to run.

Where possible, current date dependencies should be injectable or controllable.

---

# Search Tests

Customer search should be tested with realistic Turkish text.

Examples may include:

```text
İ
I
ı
i
Ş
ş
Ğ
ğ
Ü
ü
Ö
ö
Ç
ç
```

Search behavior should match the final approved normalization rules.

Names must not be modified permanently just to simplify searching.

---

# Sorting Tests

If the customer list supports sorting by:

- Name (`full_name`, then customer ID ascending)
- Highest debt (raw signed balance descending, then name and customer ID)
- Recent activity (latest non-void transaction first; customers without transactions last)
- Registration date (`registered_on` descending with NULL values last)

the underlying ordering should be tested independently from the visible table.

Special cases should include:

- Equal balances
- Zero balance
- Negative balance, presented by absolute amount as **Fazla Ödeme**
- Customers with no transactions
- Duplicate names and equal sort values
- Nullable transaction times and registration dates

Customer-summary query tests should also prove that balance and latest-transaction data are loaded
with a bounded number of set-based SQL queries independent of customer count. The read model must
retain the raw signed balance and must not expose ORM entities or SQLAlchemy row objects.

---

# Last Activity Tests

Version 1 defines customer last activity as the most recent non-voided financial transaction business date.

Tests should verify:

- Customer with no transactions has no last activity date.
- Debt transaction updates last activity.
- Payment transaction updates last activity.
- Backdated entry affects last activity only according to its business date.
- Voiding the newest transaction causes last activity to fall back to the next newest active transaction.
- Reminder creation does not change financial last activity.
- Customer profile editing does not change financial last activity.

The UI should treat this as "Last activity" / "Son işlem", not as an independent medical visit record.

# Database Constraints

Tests should verify important database constraints.

Examples:

- Transaction customer must exist
- Animal customer must exist
- Reminder customer must exist
- Required fields cannot be NULL
- Foreign keys are enforced

Where important, tests should intentionally attempt invalid database operations and verify that they fail safely.

---

# Data Deletion Tests

Important financial history must not be lost through accidental cascade deletion.

Tests should explicitly verify cases such as:

```text
Archive customer
```

does not delete:

```text
Transactions
```

and:

```text
Archive animal
```

does not delete:

```text
Historical transactions
```

Database cascade behavior must match the documented deletion policy.

---

# Error Handling Tests

Important error paths should be tested.

Examples:

- Database unavailable
- Invalid input
- Backup destination unwritable
- Invalid import database
- Missing legacy tables
- Corrupted backup
- Missing customer
- Wrong animal relationship

Tests should verify both:

1. Internal operation fails safely
2. Existing database state remains valid

---

# Logging Tests

Logging should not normally require extensive tests.

However, security-sensitive behavior may require verification that logs do not contain prohibited values.

Examples:

- Password
- Password hash
- Complete sensitive customer notes
- SQLAlchemy bound parameters and customer-derived report paths

Do not over-test exact log wording unless the wording itself is important.

---

# Performance Testing

Hesiva does not require enterprise-scale performance benchmarking.

However, representative datasets should occasionally be tested.

Useful synthetic sizes may include:

```text
1,000 customers
10,000 transactions
50,000 transactions
100,000 transactions
```

Important operations include:

- Application startup
- Customer search
- Customer history loading
- Balance calculation
- Sorting by balance
- Yearly report generation
- Legacy import

Performance tests exist to detect obviously poor behavior, not to chase arbitrary benchmark numbers.

---

# Target Hardware Testing

Before stable release, the application should be tested on hardware representative of the production computer.

Important characteristics include:

- Older CPU
- 4 GB RAM
- SSD
- 1366x768 display
- Linux desktop environment

Development on a faster computer alone is not sufficient evidence of acceptable performance.

---

# Linux Testing

Linux is the primary platform.

Stable releases should be tested for:

- Startup
- Database access
- Fonts
- Window sizing
- Keyboard navigation
- Backup
- Restore
- PDF generation
- Printing if available
- Packaging
- File permissions

Primary production testing should occur on the intended Linux distribution once selected.

---

# Windows Testing

Windows is secondary but supported.

Before a Windows build is considered usable, test:

- Startup
- Database location
- Path handling
- Backup
- Restore
- PDF generation
- Packaging
- Turkish characters

Linux-specific assumptions must not leak into general business logic.

# Packaged Runtime Testing

Source tests are necessary but do not prove that dynamic Alembic resources, Qt plugins, package
metadata, or native libraries survived freezing. A release candidate therefore follows this order:

```text
pytest and Ruff
        ↓
clean PyInstaller onedir build
        ↓
actual user executable launch with isolated HOME/XDG_DATA_HOME
        ↓
separately frozen end-to-end runtime smoke
        ↓
bundle-content and shared-library inspection
```

The clean build records source and complete-runtime digests. Smoke and Debian staging verify that
record before using the artifact, and staging verifies the copied runtime again; tests deliberately
mutate application source, the platform release icon inputs, and runtime fixtures to ensure
stale/substituted artifacts are rejected. Windows builds invoke the same portable provenance helper
around native PyInstaller rather than relying on Linux-only shell behavior. The
actual user executable's fresh database is checked for SQLite integrity, the complete table set,
and current migration head. Its Qt backing-store diagnostic must also prove that first-run reached
a top-level UI surface rather than merely being assumed healthy because the process stayed open.

The separately frozen packaged smoke covers fresh database migration, first password creation,
empty setup, reopen and login, password change, customer/debt/balance behavior, PDF output,
backup/restore of database and
configuration, Settings/About/version, and synthetic Veresiye 5 import. It verifies that the release
tree remains byte-identical and that no user state appears beside the executable. The synthetic
legacy builder exists only in the development smoke bundle, never in the production artifact.

Linux smoke on one development host is not a clean-machine compatibility claim. Before release,
repeat it on the selected older glibc baseline, the representative Intel i3-540/4 GB system, and the
chosen Linux desktop/print environment. Windows requires a native Windows x86_64 build followed by
the corresponding startup, path, authentication, CRUD, PDF/print, backup/restore, import, and
uninstall-preservation checks.

Release-resource tests also validate the master and generated icon dimensions/transparency,
source/frozen icon resolution, desktop-entry semantics, Debian metadata/layout mappings, MIT
metadata consistency, and the absence of user-data cleanup scripts or developer-specific paths.
`desktop-file-validate` and `dpkg-deb` inspection remain build-host validation steps rather than unit
tests of those system tools.

---

# Automated Test Command

The complete automated test suite should be executable with one clear command.

For example:

```bash
pytest
```

Developers and AI coding tools should not need to manually run many unrelated scripts to determine whether the project is healthy.

---

# Fast Development Test Loop

During development, focused tests may be run.

Example:

```bash
pytest tests/integration/test_transactions.py
```

Before considering a feature complete, the appropriate broader suite should also pass.

---

# Lint and Formatting Checks

Testing completion also includes static quality checks.

At minimum:

```bash
ruff check .
ruff format --check .
pytest
```

should succeed before a change is considered complete.

The exact commands may later be wrapped in a project script.

---

# Continuous Integration

GitHub Actions may be introduced to run automated checks on repository changes.

A basic CI workflow may run:

```text
Install project
↓
Ruff
↓
Tests
```

CI should remain simple.

The application does not require a complex deployment pipeline.

Primary goals are:

- Catch broken commits
- Detect formatting problems
- Run automated tests in a clean environment

---

# Feature Completion Criteria

A feature is not complete when:

```text
The button works once.
```

A feature is complete when:

- Required behavior is implemented
- Error paths are handled
- Data remains consistent
- Relevant automated tests exist
- Tests pass
- Ruff passes
- Manual UI checks are performed when relevant
- Documentation still matches actual behavior

---

# Regression Tests

When a bug is found, a regression test should normally be added before or together with the fix.

Example:

Bug:

```text
Payment of 300.50 TL becomes 300.49 TL
```

Before fixing:

Create a test reproducing the bug.

Then fix the implementation.

The test prevents the same defect from returning later.

---

# Critical Regression Areas

Special care should be taken when modifying:

- Money parsing
- Balance calculation
- Signed financial movement direction
- Database relationships
- Import mapping
- Backup
- Restore
- Migrations
- Date filtering
- Report totals

Changes in these areas should run the relevant complete test groups.

---

# Random Testing

Randomized testing may be used for financial invariants if useful.

For example:

Generate many synthetic debt and payment transactions.

Verify:

```text
Reported balance
=
Sum of financial movements
```

Random tests must use deterministic seeds when reproducibility is required.

Random testing supplements explicit business examples.

It does not replace them.

---

# Test Fixtures

Reusable fixtures may provide:

- Temporary database
- SQLAlchemy session
- Customer factory
- Animal factory
- Transaction factory
- Synthetic legacy database
- Temporary backup directory

Fixtures should simplify test setup without hiding important behavior.

Avoid deeply nested fixture systems that make tests difficult to understand.

---

# Mocking

Mocks should be used selectively.

Good uses may include:

- Simulating an unavailable external filesystem operation
- Preventing an actual print operation
- Isolating a UI from a service

Avoid mocking the database in tests whose purpose is to verify database behavior.

SQLite integration is a core part of Hesiva and should be tested directly.

---

# Test Readability

A test should make its scenario obvious.

Preferred structure:

```text
Arrange
Create required state

Act
Perform one operation

Assert
Verify the result
```

Comments such as `Arrange`, `Act`, and `Assert` are optional.

The structure itself should be clear.

---

# Test Naming

Test names should describe the behavior.

Good:

```python
def test_payment_reduces_outstanding_balance() -> None:
    ...
```

Good:

```python
def test_import_rolls_back_when_transaction_mapping_fails() -> None:
    ...
```

Bad:

```python
def test_1() -> None:
    ...
```

Bad:

```python
def test_customer() -> None:
    ...
```

---

# Test Failure Messages

Assertions should provide enough information to understand a failure.

Avoid excessive custom messages when pytest's normal assertion output already explains the problem.

For complex reconciliation tests, useful diagnostic values should be included.

Example:

```text
Expected transactions: 12,534
Imported transactions: 12,531
```

This is more useful than:

```text
Import failed.
```

---

# No Production Side Effects

Running tests must never:

- Modify production database
- Delete production backups
- Change actual application password
- Write to production application directories
- Modify real legacy backups
- Print real documents
- Send network requests unless explicitly part of a future test

Test environment boundaries must be explicit.

---

# Destructive Test Safety

Tests involving:

- Restore
- Migration
- Archive
- Voiding
- Import rollback

must operate only on temporary test data.

Any destructive testing utility must refuse production locations if there is a realistic risk of accidental misuse.

---

# Manual Acceptance Checklist

Before a stable release, perform a manual acceptance test covering the core workflow.

Example:

```text
Launch application
↓
Log in
↓
Create customer
↓
Find customer through search
↓
Create debt transaction
↓
Verify balance
↓
Create second transaction
↓
Receive payment
↓
Verify balance
↓
Add animal
↓
Create transaction associated with animal
↓
Create reminder
↓
Restart application
↓
Verify data remains
↓
Verify reminder
↓
Generate customer statement
↓
Create backup
↓
Verify backup
```

The exact checklist should evolve with the application.

---

# Legacy Migration Acceptance Test

Before using Hesiva with the real business database, perform a dedicated migration rehearsal.

The recommended process is:

```text
Copy legacy backup
↓
Import into test Hesiva database
↓
Do not modify original legacy backup
↓
Compare customer counts
↓
Compare transaction counts
↓
Compare debt totals
↓
Compare payment totals
↓
Compare sample customer balances
↓
Inspect historical transactions
↓
Generate import report
```

Only after reconciliation succeeds should the production migration be considered ready.

---

# Sample Customer Verification

During the migration rehearsal, manually select representative customers such as:

- Customer with no debt
- Customer with current debt
- Customer with many years of history
- Customer with many payments
- Customer with duplicate name
- Customer with very old transactions
- Customer with recent transactions

Compare old and new systems side by side.

Sensitive real data used for this manual migration verification must not be committed to Git.

---

# Backup Recovery Rehearsal

Before relying on the backup system in production, perform a real recovery rehearsal.

A backup system is not considered trustworthy until restoration has been tested.

Example:

```text
Create test data
↓
Create backup
↓
Simulate database loss
↓
Restore backup
↓
Verify all records
```

This should be repeated after significant changes to backup or database architecture.

---

# Test Coverage

A numeric coverage percentage is not the primary goal.

100% line coverage can still miss important business errors.

Coverage tools may be used to identify completely untested areas.

However, acceptance criteria should focus on whether important behavior is protected.

A lower percentage with strong financial and data-integrity tests is more valuable than a high percentage dominated by trivial code.

---

# What Does Not Need Extensive Testing

Simple presentation-only code may not require detailed automated testing.

Examples:

- Static label text
- Decorative spacing
- Minor visual styling
- Simple icon selection

Do not spend more testing effort on cosmetic code than on financial integrity.

---

# AI-Assisted Testing

AI-generated implementation must include appropriate tests.

AI tools must not:

- Delete failing tests to make the suite pass
- Weaken assertions without justification
- Skip tests simply because implementation is difficult
- Replace important integration tests with meaningless mocks
- Modify expected values to match incorrect implementation

When an existing test conflicts with a new requirement, the requirement and test should be reviewed explicitly.

AI tools should explain why a test needs to change instead of silently changing expected behavior.

---

# Test-Driven Bug Fixes

For reproducible bugs, the preferred workflow is:

```text
Reproduce bug
↓
Create failing regression test
↓
Confirm test fails
↓
Implement fix
↓
Confirm test passes
↓
Run related tests
```

This provides evidence that the fix addresses the actual defect.

---

# Test Maintenance

Tests are production assets.

They should be maintained with the same care as application code.

Remove tests only when:

- The associated behavior no longer exists
- Requirements intentionally changed
- A better test completely replaces them

Do not remove a test simply because it becomes inconvenient.

---

# V1 Minimum Test Areas

Before Hesiva Version 1.0 is considered stable, automated tests should cover at minimum:

- Customer creation
- Customer modification
- Customer archiving
- Customer search
- Debt transaction creation
- Payment creation
- Balance calculation
- Money parsing
- Money formatting
- Transaction void/correction behavior
- Animal ownership
- Reminders
- Authentication
- Legacy customer import
- Legacy transaction import
- Import rollback
- Import reconciliation
- Backup creation
- Backup verification
- Restore
- Database migrations
- Annual financial totals
- Monthly financial totals

Manual acceptance testing should additionally cover the complete primary user workflow.

---

# Release Testing Gate

A stable release must not be produced if any critical test is failing.

Critical failures include:

- Incorrect balance
- Lost transaction
- Failed migration
- Invalid backup
- Broken restore
- Incorrect legacy import
- Authentication bypass
- Data relationship corruption

Cosmetic defects may be evaluated separately.

Data-integrity defects block release.

---

# Summary

Hesiva testing follows one primary principle:

> The software must prove that it preserves financial and customer data correctly.

The preferred testing hierarchy is:

```text
Business logic
        ↓
Database integration
        ↓
Critical UI behavior
        ↓
Manual acceptance
```

Automated testing focuses primarily on:

```text
Money
Transactions
Balances
Relationships
Import
Backup
Restore
Migrations
Reports
```

Tests use temporary databases and synthetic data.

Production data is never part of the automated test suite.

A backup is not considered valid until it can be restored.

An import is not considered valid until historical totals can be reconciled.

A financial feature is not considered complete until its important behavior is covered by tests.

The purpose of the test suite is not to make development slower.

Its purpose is to allow Hesiva to evolve without silently breaking the business history it exists to protect.
