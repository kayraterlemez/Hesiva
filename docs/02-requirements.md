# Software Requirements Specification (SRS)

## Introduction

This document defines the functional and non-functional requirements for the Hesiva desktop application.

Hesiva is a local-first desktop application used to track customers, optional animals, financial movements, reminders, reports, backups, and migration from the legacy Veresiye 5 application.

Version 1 is intentionally focused. Inventory, medical records, cloud synchronization, and multi-user networking are outside the Version 1 scope.

---

# Functional Requirements

## Customer Management

### REQ-001

The application shall allow users to create customers.

Priority: Critical

---

### REQ-002

The application shall allow users to edit customer information.

Priority: High

---

### REQ-003

The application shall allow users to archive customers without deleting their history.

Archived customers shall retain their transactions, animals, and reminders.

The application shall allow an archived customer to be unarchived. Unarchiving sets
`archived_at` back to NULL and does not automatically unarchive any animals.

Priority: High

---

### REQ-004

The application shall provide instant customer search.

Priority: Critical

---

### REQ-005

The application shall allow sorting customers by:

- Name
- Outstanding balance
- Last activity
- Creation/registration date

Priority: High

---

### REQ-006

The customer balance displayed by the application shall always be derived from active financial transactions.

A mutable stored balance field shall not be treated as authoritative.

Priority: Critical

---

## Animal Management

### REQ-007

A customer shall be able to have zero or more animals.

Priority: High

---

### REQ-008

Animal information may contain:

- Ear tag number
- Name
- Species
- Notes

These fields are optional unless later business rules explicitly require otherwise.

Priority: High

---

### REQ-009

A transaction may optionally reference one animal belonging to the same customer.

A transaction shall never reference an animal owned by another customer.

Priority: Critical

---

### REQ-010

Animals shall be archived rather than physically deleted when historical transactions reference them.

The application shall allow an archived animal to be unarchived only while its owning customer is
active. It shall not automatically unarchive the owning customer.

Priority: High

---

## Transactions

### REQ-011

The application shall allow users to add debt transactions.

Priority: Critical

---

### REQ-012

The application shall allow users to record payments.

Priority: Critical

---

### REQ-013

Financial movement direction shall be represented by the sign of the stored amount:

- Debt: positive amount
- Payment: negative amount

The normal payment UI shall accept a positive amount from the user and convert it to a negative stored movement exactly once.

Priority: Critical

---

### REQ-014

Every financial transaction shall contain:

- Customer
- Business date
- Free-text description
- Non-zero amount
- Optional animal
- Optional note

Priority: Critical

---

### REQ-015

Transaction descriptions shall remain unrestricted free text rather than catalog-controlled text.
Like all persisted user-entered business text, they remain subject only to the shared 1 MiB UTF-8
technical safety ceiling.

Version 1 shall not require catalog or predefined product/service entries.

Priority: Critical

---

### REQ-016

Version 1 shall not allow users to directly edit an existing financial transaction.

To correct an incorrect transaction, the user shall void the existing transaction and create a new
correct transaction when required.

The voided transaction shall remain stored as historical data and shall not affect the active
balance.

Priority: High

---

### REQ-017

Users shall be able to void an incorrect transaction without physically deleting it.

Voided transactions shall remain available for historical/reference purposes but shall not affect active balances or reports.

A void reason may be recorded but shall remain optional.

Priority: High

---

### REQ-018

Payments are not allocated to individual debt transactions.

A payment reduces the customer's overall account balance.

Priority: Critical

---

### REQ-019

The application shall support negative customer balances.

A negative balance represents customer credit and may occur after an overpayment or after importing
valid legacy history. Internal balance values remain signed: positive is debt, zero is neutral, and
negative is overpayment/customer credit.

The user interface shall present a positive balance as **Borç**, zero as a neutral zero balance, and
a negative balance as its absolute amount labeled **Fazla Ödeme**. **Alacak** shall not be used as
the normal user-facing negative-balance label.

Priority: High

---

### REQ-020

The application's "last activity" value shall mean the most recent non-voided financial transaction date for the customer.

It is not a separate medical or physical-visit record.

Priority: High

---

## Reminders

### REQ-021

Users shall be able to create reminders associated with customers.

Priority: High

---

### REQ-022

The application shall show due and overdue reminders when launched and inside the application.

After authentication succeeds and the Main Window is available, Version 1 shows at most one
startup summary containing application-wide counts for active overdue reminders and active
reminders due on the current local date. Completed, cancelled, and future reminders are excluded.
No startup dialog is shown when both counts are zero, and the midnight presentation refresh does
not repeat the startup dialog.

Operating-system desktop notifications are optional.

Priority: High

---

### REQ-023

Each reminder shall contain:

- Reminder date
- Customer
- Note
- Completion state

Completed reminders shall remain stored.

Priority: High

---

## Reports

### REQ-024

The application shall generate printable customer account statements containing transaction history and account totals.

Priority: High

---

### REQ-025

The application shall export customer account statements as PDF.

Priority: High

---

### REQ-026

The application shall provide basic monthly and yearly financial summaries for Version 1.

Monthly and yearly summaries shall support local PDF export and standard printing.

At minimum, summaries shall report:

- Debt created during the selected period
- Payments received during the selected period
- Net financial movement

The application shall not claim that payments received in a period necessarily paid debts created in the same period because Version 1 does not allocate payments to individual debts.

Priority: Medium

---

## Security

### REQ-027

The application shall require a locally configured password before normal access.

The first launch shall ask the user to create the password.

Priority: High

---

### REQ-028

Passwords shall never be stored in plain text.

Passwords shall be stored only as encoded Argon2id hashes in the application-data `config.json`.
Production hashing uses time cost 3, memory cost 65536 KiB, parallelism 4, hash length 32, and salt
length 16.

Priority: Critical

---

### REQ-029

After successful authentication, Version 1 shall remain unlocked until the application is closed.

Automatic inactivity locking is not required for Version 1.

Priority: Medium

---

### REQ-030

The application password provides application-level access control only.

It shall not be described as encryption of the SQLite database.

Priority: High

---

### V1 Authentication State Contract

First run shall create the local password before offering **Boş Veritabanıyla Başla** or **Eski
Veresiye 5 Verilerini İçe Aktar**. Password creation persists an incomplete setup state; completing
either choice marks setup complete. Reopening an incomplete setup requires the existing password and
then resumes or safely finalizes setup without creating a second password.

A current populated business database with missing, malformed, or unusable authentication
configuration shall be blocked without modifying business data. A populated database with a valid
password and incomplete setup is recoverable after login.

Version 1 shall not provide password reset, recovery, hints, default credentials, or backdoors.

---

## Backup

### REQ-031

Automatic backups shall be supported.

Version 1 performs one startup-time check after authentication. It creates at most one successful
normal automatic backup per local calendar day in `<application-data>/backups` and retains verified
normal automatic backups from the most recent 30 calendar days. Manual backups, restore safety
backups, ambiguous files, and unrelated files are outside automatic retention. Failure does not
block normal startup and is reported once with a concise manual-backup recommendation.

Priority: Critical

---

### REQ-032

Manual backups shall be supported.

Priority: High

---

### REQ-033

Users shall be able to restore verified backups.

Priority: Critical

---

### REQ-034

SQLite backups shall be created using a SQLite-safe snapshot/backup mechanism.

The application shall not treat a raw copy of an active database file as a valid backup strategy.

Priority: Critical

---

### REQ-035

Before migrations, legacy import, and restore operations, the application shall create an appropriate recovery backup when a current database exists.

Priority: Critical

---

### REQ-036

The application shall allow the user to choose a backup destination and should recommend a destination on a different physical device when available.

A same-device backup may be used as a fallback but shall not be presented as protection against disk failure.

The preferred manual-backup directory is stored as the optional
`backup.destination_directory` configuration value. Missing or `null` uses Hesiva's established
local backup directory. Changing the preference takes effect immediately for future manual backups,
does not move or create a backup, and requires no restart. If a configured directory is unavailable,
manual backup shall fail clearly without silently falling back; startup, authentication, and normal
business-data access remain available.

Priority: High

---

### V1 Settings and About Contract

Version 1 Settings contains only password change, preferred manual-backup location, and the current
application version. About displays **Hesiva**, the version obtained from `pyproject.toml`
`project.version`, and **Veteriner müşteri hesap ve bakiye takip uygulaması.** Version 1 has no
separate build identifier. About identifies the authoritative release license concisely as
**MIT Lisansı**; the complete legal text remains in `LICENSE`.

---

## Import

### REQ-037

Version 1 shall support one-time migration from Veresiye 5 legacy data.

Priority: Critical

---

### REQ-038

The legacy source shall always be opened read-only and shall never be modified by the importer.

Version 1 supports the validated Veresiye 5 framed `.exa` profile containing exactly one
`Frm1.edb`, plus direct `.edb` selection as an advanced path. Unknown container flags, framing,
schema shapes, dates, times, encodings, and monetary representations shall be rejected rather than
guessed. Legacy text in this profile is decoded strictly as Windows-1254/CP1254.

Priority: Critical

---

### REQ-039

Version 1 legacy migration shall preserve historical customers and financial movements, including original business dates, descriptions, amounts, and customer relationships whenever valid source data is available.

Two explicitly classified non-business source rows are excluded and counted: structurally empty,
unreferenced placeholder customer cards and zero-movement `Data` rows. The importer shall not
create fake customer names or fake nonzero transactions for either category.

Priority: Critical

---

### REQ-040

Legacy customer and transaction identifiers shall be preserved as optional reference metadata (`legacy_id`) but shall never become current primary keys.

Priority: High

---

### REQ-041

Legacy stored summary values such as debt, credit, and balance shall be used only for reconciliation.

The new application's authoritative balance shall be recalculated from imported financial movements.

Priority: Critical

---

### REQ-042

Version 1 legacy import is intended for an empty Hesiva business database.

Merging a complete legacy database into an already active Hesiva business database is outside the Version 1 scope.

Priority: High

---

### REQ-043

A critical import failure shall roll back the migration so that no partial production import remains.

The destination write shall use one transaction and shall be committed only after customer and
transaction counts, legacy-ID mappings, foreign keys, global debt/payment/net totals, and
per-customer debt/payment/net totals reconcile.

Priority: Critical

---

## Data Preservation

### REQ-044

Important business history shall not be physically deleted during normal application use.

The normal lifecycle shall use:

- Customer archive
- Animal archive
- Transaction void
- Reminder completion

Priority: Critical

---

### REQ-045

All database operations that form one logical business action shall be atomic.

A failure shall not leave partially written business data.

Priority: Critical

---

# Non-Functional Requirements

### NFR-001 — Offline Operation

Normal operation shall require no Internet connection, cloud service, or external server.

---

### NFR-002 — Primary Platform

Linux is the primary supported platform.

Windows is a secondary supported platform.

---

### NFR-003 — Target Hardware

The application shall remain practical on older hardware with approximately:

- Intel Core i3-class CPU
- 4 GB RAM
- SSD storage
- 1366×768 display

---

### NFR-004 — Responsiveness

Normal customer search, customer selection, transaction entry, and payment entry should feel immediate.

Long-running operations such as import, restore, and large reports shall not leave the interface appearing permanently frozen.

---

### NFR-005 — Data Integrity

Data integrity has higher priority than cosmetic behavior and micro-optimizations.

---

### NFR-006 — Privacy

The application shall not include telemetry, advertising, user tracking, or automatic transmission of customer information.

---

### NFR-007 — Maintainability

The implementation shall follow `09-architecture.md`, `10-coding-style.md`, and `11-testing.md`.

Major architectural changes require explicit review.
