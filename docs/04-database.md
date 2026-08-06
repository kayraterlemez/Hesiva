# Database Design

## Purpose

This document defines the logical database design of the Cari application.

The database is designed for a single-user, offline-first desktop application that must preserve customer and financial history reliably for many years.

Version 1 intentionally uses a simple ledger model that matches the real workflow of the legacy application.

The database design prioritizes:

1. Data integrity
2. Simplicity
3. Recoverability
4. Long-term maintainability
5. Performance

---

# Database Design Principles

## DB-001 — Financial history is the source of truth

A customer's balance shall not exist as an authoritative mutable customer field.

The balance is calculated from active financial transactions.

This guarantees that a displayed balance can be reproduced from stored history.

---

## DB-002 — One transaction equals one financial movement

Version 1 does not use `TransactionItem`, line-item grouping, or a product catalog.

A normal daily entry is intentionally simple:

```text
Date
Description
Amount
Optional animal
Optional note
```

Examples:

```text
Birth + Medicine    +1500 TL
Treatment            +500 TL
Payment              -300 TL
```

---

## DB-003 — Signed integer money

Authoritative monetary values are stored as integer kuruş.

Binary floating-point values must never be used for stored money.

```text
1 TL = 100 kuruş
1500.00 TL = 150000
```

Financial direction is represented by the sign:

- Positive amount → debt/charge
- Negative amount → payment/credit
- Zero → invalid financial movement

A negative final customer balance is allowed and represents customer credit.

---

## DB-004 — Historical financial records are not physically deleted

Incorrect transactions are voided rather than physically removed.

Voided transactions remain available for historical/reference purposes but do not affect active balances or normal financial reports.

Customers and animals are archived instead of being physically deleted when history depends on them.

---

## DB-005 — Business dates are separate from technical timestamps

The date on which a financial movement belongs to the business account is stored separately from record creation/update timestamps.

This is required because users may enter an older transaction after the fact and because legacy transactions must preserve their original dates.

---

## DB-006 — Legacy identifiers are references only

Imported Veresiye 5 identifiers may be stored in nullable `legacy_id` fields.

They exist for:

- Migration verification
- Troubleshooting
- Duplicate migration protection
- Comparison with the legacy application

They are never used as the primary identity system of Cari.

---

## DB-007 — Database-enforced relationships

SQLite foreign key enforcement must be enabled.

Important relationships should be protected both by application validation and database constraints where practical.

Cascade deletion must never accidentally remove financial history.

---

# Entity: Customer

## Purpose

Represents a customer whose account is tracked by Cari.

Customers are the center of the application.

A customer may own zero or more animals, financial transactions, and reminders.

---

## Fields

| Field | Type | Description |
| --- | --- | --- |
| id | Integer | Primary key |
| legacy_id | Integer / NULL | Original Veresiye 5 customer ID when imported |
| full_name | Text | Customer name |
| phone | Text / NULL | Phone number |
| address | Text / NULL | Address |
| notes | Text / NULL | Additional notes |
| registered_on | Date / NULL | Business registration date when known |
| created_at | DateTime | Cari record creation timestamp |
| updated_at | DateTime | Last modification timestamp |
| archived | Boolean | Archive flag |

---

## Business Rules

- `full_name` is required.
- Human names are not unique; two customers may have the same name.
- `legacy_id` is normally NULL for customers created directly in Cari.
- Customers are archived rather than physically deleted.
- Archiving a customer does not delete animals, reminders, or transactions.
- Customer balance is calculated from active transactions.
- Last activity is calculated from the most recent non-voided transaction business date.

---

# Entity: Animal

## Purpose

Represents an optional animal belonging to a customer.

Animals exist to help identify which animal a financial movement concerned.

Cari Version 1 is not a medical record system.

---

## Fields

| Field | Type | Description |
| --- | --- | --- |
| id | Integer | Primary key |
| customer_id | Integer | Owner customer foreign key |
| ear_tag | Text / NULL | Ear tag number |
| name | Text / NULL | Optional animal name |
| species | Text / NULL | Optional species |
| notes | Text / NULL | Optional notes |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last modification timestamp |
| archived | Boolean | Archive flag |

---

## Business Rules

- Every animal belongs to exactly one customer.
- A customer may own zero or more animals.
- Animal fields may remain optional unless future requirements explicitly change this.
- A financial transaction may reference an animal.
- A transaction's animal must belong to the same customer as the transaction.
- Animals are archived rather than physically deleted when history references them.

---

# Entity: Transaction

## Purpose

Represents one financial movement in a customer's account.

This entity is intentionally close to the legacy daily workflow:

```text
Customer
Date
Description
Amount
```

with optional animal and note information.

---

## Fields

| Field | Type | Description |
| --- | --- | --- |
| id | Integer | Primary key |
| legacy_id | Integer / NULL | Original Veresiye 5 transaction ID when imported |
| customer_id | Integer | Customer foreign key |
| animal_id | Integer / NULL | Optional animal foreign key |
| transaction_date | Date | Business date |
| transaction_time | Time / NULL | Optional time used for stable same-day ordering/import preservation |
| description | Text | Free-text description |
| amount_kurus | Integer | Signed non-zero monetary movement in kuruş |
| note | Text / NULL | Optional note |
| created_at | DateTime | Cari record creation timestamp |
| updated_at | DateTime | Last modification timestamp |
| voided_at | DateTime / NULL | When the movement was voided |
| void_reason | Text / NULL | Optional correction/void reason |

---

## Business Rules

- Every transaction belongs to exactly one customer.
- `description` is required.
- `amount_kurus` must never be zero.
- Positive amounts increase outstanding debt.
- Negative amounts reduce outstanding debt.
- Payments are not allocated to individual debt transactions.
- A negative total balance is valid and represents customer credit.
- A transaction may optionally reference an animal belonging to the same customer.
- New transactions may set `transaction_time` automatically to the current local time; the user does not need to enter it manually.
- Legacy import may preserve the original legacy time when valid.
- Voided transactions remain stored but do not affect active balance, last activity, or normal report totals.
- Transactions are never physically deleted during normal use.
- Editing a transaction is a correction operation and updates `updated_at`.

---

# Balance Calculation

The authoritative balance is derived from non-voided transactions:

```text
balance_kurus = SUM(amount_kurus)
```

Example:

```text
+50000
+40000
+60000
-50000
```

represents:

```text
+500 TL
+400 TL
+600 TL
-500 TL
```

and produces:

```text
1000 TL outstanding balance
```

No separate mutable balance field exists on `Customer`.

---

# Debt and Payment Totals

For reporting:

```text
Debt total =
SUM(amount_kurus WHERE amount_kurus > 0 AND transaction is active)

Payment total =
ABS(SUM(amount_kurus WHERE amount_kurus < 0 AND transaction is active))
```

Period reports filter by `transaction_date`.

Payments are not matched to individual debt records.

---

# Last Activity

Version 1 defines customer last activity as:

```text
MAX(transaction_date)
```

over the customer's non-voided financial transactions.

This field is calculated, not stored as a separate customer value.

It should be described in the UI as "Last activity" / "Son işlem", not as a separate medical visit record.

---

# Entity: Reminder

## Purpose

Stores future reminders associated with customers.

The primary Version 1 use case is a payment reminder.

---

## Fields

| Field | Type | Description |
| --- | --- | --- |
| id | Integer | Primary key |
| customer_id | Integer | Related customer foreign key |
| remind_on | Date | Reminder date |
| note | Text | Reminder description |
| completed | Boolean | Completion state |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last modification timestamp |

---

## Business Rules

- Every reminder belongs to exactly one customer.
- `remind_on` and `note` are required.
- Completed reminders remain stored.
- Completed reminders are excluded from the active due-reminder list.
- Reminder processing does not require Internet access.

---

# Application Configuration

Application configuration is logically separate from business entities.

Version 1 does not require a generic `Settings` business table.

Configuration may be stored in a platform-appropriate application configuration file and may include:

- Password hash
- Backup destination
- Window state
- UI preferences
- Application settings

Configuration storage must use atomic/safe file-writing practices where appropriate.

The application password hash provides application-level access control; it does not encrypt the SQLite database.

---

# Legacy Data Mapping

Known Veresiye 5 data maps conceptually as follows:

```text
CariKart → Customer
Data     → Transaction
```

Useful legacy identifiers are preserved in `legacy_id`.

Legacy customer summary fields such as:

```text
Borc
Alacak
Bakiye
STarih
```

are not imported as authoritative current fields.

They may be used during migration reconciliation.

Legacy transaction rows are converted to signed `amount_kurus` values.

---

# Indexes

Indexes should support actual application queries rather than being added indiscriminately.

Expected useful indexes include:

- `customer.full_name`
- `customer.legacy_id`
- `animal.customer_id`
- `transaction.customer_id`
- `transaction.transaction_date`
- `transaction.legacy_id`
- `reminder.customer_id`
- `reminder.remind_on`

Search-specific indexing may be adjusted after representative performance testing.

---

# Constraints

Important constraints should include:

- Foreign key enforcement enabled
- Required customer name
- Required transaction description
- Non-zero `amount_kurus`
- Required transaction customer
- Required reminder customer/date/note
- Animal owner required

The service layer must additionally validate that a selected animal belongs to the transaction customer.

---

# Version 1 Boundaries

Version 1 intentionally does not contain:

- TransactionItem
- CatalogItem
- Inventory
- Medicine stock tracking
- Medical records
- Suppliers
- Purchase orders
- Multi-user server data
- Cloud synchronization

These may be considered later only if a concrete need appears.

The Version 1 schema should not become more complicated merely to anticipate hypothetical future modules.

---

# Summary

The Version 1 database is centered on a simple ledger:

```text
Customer
    ├── Animal (optional)
    ├── Transaction
    └── Reminder
```

A transaction is one signed financial movement.

Customer balances are calculated from non-voided transaction history.

Money is stored as integer kuruş.

Legacy IDs are preserved only as migration references.

Important history is archived or voided rather than physically deleted.

This design intentionally matches the real daily workflow while removing the redundant stored balance and line-item complexity of the earlier draft.
