# Software Requirements Specification (SRS)

## Introduction

This document defines the functional and non-functional requirements for the Cari desktop application.

Cari is a local-first desktop application used to track customers, optional animals, financial movements, reminders, reports, backups, and migration from the legacy Veresiye 5 application.

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

Transaction descriptions shall remain unrestricted free text.

Version 1 shall not require catalog or predefined product/service entries.

Priority: Critical

---

### REQ-016

Users shall be able to correct an existing transaction.

Editing must update the calculated balance immediately and must not affect another customer's records.

Priority: High

---

### REQ-017

Users shall be able to void an incorrect transaction without physically deleting it.

Voided transactions shall remain available for historical/reference purposes but shall not affect active balances or reports.

Priority: High

---

### REQ-018

Payments are not allocated to individual debt transactions.

A payment reduces the customer's overall account balance.

Priority: Critical

---

### REQ-019

The application shall support negative customer balances.

A negative balance represents customer credit and may occur after an overpayment or after importing valid legacy history.

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

Argon2id is the preferred password hashing algorithm.

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

## Backup

### REQ-031

Automatic backups shall be supported.

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

Priority: High

---

## Import

### REQ-037

Version 1 shall support one-time migration from Veresiye 5 legacy data.

Priority: Critical

---

### REQ-038

The legacy source shall always be opened read-only and shall never be modified by the importer.

Priority: Critical

---

### REQ-039

Version 1 legacy migration shall preserve historical customers and financial movements, including original business dates, descriptions, amounts, and customer relationships whenever valid source data is available.

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

Version 1 legacy import is intended for an empty Cari business database.

Merging a complete legacy database into an already active Cari business database is outside the Version 1 scope.

Priority: High

---

### REQ-043

A critical import failure shall roll back the migration so that no partial production import remains.

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
