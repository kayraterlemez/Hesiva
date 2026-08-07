# Import System

## Purpose

The import system migrates the existing Veresiye 5 customer and financial history into Cari.

This is a critical Version 1 requirement because Cari cannot safely replace the legacy application if years of account history disappear during transition.

The importer must preserve business history while keeping the original legacy source unchanged.

---

# Import Scope

Version 1 supports a one-time Veresiye 5 migration.

Primary user-facing source:

- Veresiye 5 backup (`.exa`)

Validated internal/source database format:

- SQLite database stored with an `.edb` extension

Version 1 is not a general CSV/Excel importer.

Additional import formats may be considered later.

---

# Known Legacy Structure

Observed Veresiye 5 data is stored in SQLite databases despite the `.edb` extension.

Known tables include:

```text
CariKart
Data
ATemp
```

Additional legacy database files may include tables such as:

```text
Firma
Setting
```

For Cari migration, the important Version 1 business tables are:

```text
CariKart → customers
Data     → financial movements
```

`ATemp` and legacy application/configuration tables are not required for the core financial migration.

The importer must validate actual table/column structure instead of trusting the filename extension alone.

---

# Source Protection

The original `.exa` and `.edb` source files are immutable from Cari's point of view.

The importer shall:

- Open SQLite source databases read-only
- Never execute write statements against the legacy source
- Never rename or replace the original source
- Extract archive contents only into controlled temporary locations
- Remove temporary extracted copies when they are no longer required

The original legacy backup remains available for independent recovery/comparison.

---

# Version 1 Migration Model

Version 1 migration is intended for a new/empty Cari business database.

This is deliberate.

Merging a complete historical Veresiye 5 database into an already active Cari database introduces complex duplicate and conflict rules that are unnecessary for the initial replacement project.

Therefore:

- Initial migration into an empty Cari business database is supported.
- Re-running the same complete migration into a database that already contains imported/active business data is blocked.
- General merge/import into a non-empty production database is outside Version 1.

This keeps migration deterministic and easier to verify.

---

# Import Wizard

Recommended workflow:

```text
Select Veresiye 5 backup
        ↓
Analyze source
        ↓
Show source summary
        ↓
Validate destination is suitable
        ↓
Confirm migration
        ↓
Import customers
        ↓
Import financial movements
        ↓
Reconcile totals
        ↓
Show import report
        ↓
Finish
```

The user should see clear progress for operations that take noticeable time.

---

# Source Analysis

Before migration begins, the importer verifies:

- Source file exists
- `.exa` structure can be read when applicable
- Required `.edb`/SQLite database is present
- SQLite database opens read-only
- Required tables exist
- Required columns exist
- Database is structurally readable
- Destination database is suitable for Version 1 migration

If the source structure is unsupported, import stops before writing current business data.

---

# Customer Mapping

Known `CariKart` fields include values such as:

```text
ID
Tarih
Kod
Unvan
Yetkili
Gsm
Tel
Adres
İl
İlçe
CNot
STarih
Borc
Alacak
Bakiye
```

Version 1 mapping should preserve useful business information without reproducing obsolete accounting fields.

Recommended mapping:

| Veresiye 5 | Cari |
| --- | --- |
| `ID` | `Customer.legacy_id` |
| `Unvan` | `Customer.full_name` |
| `Gsm` | Preferred phone when present |
| `Tel` | Phone fallback when `Gsm` is empty |
| `Adres`, `İlçe`, `İl` | Combined/preserved customer address |
| `CNot` | `Customer.notes` |
| `Tarih` | `Customer.registered_on` when valid |

Other identity fields may be preserved only if a concrete Version 1 requirement exists.

Legacy summary fields:

```text
Borc
Alacak
Bakiye
STarih
```

are **not** copied as authoritative current values.

They are used only when helpful for reconciliation.

---

# Transaction Mapping

Known `Data` fields include:

```text
ID
Tarih
Saat
Tur
Unvan
Aciklama
Borc
Alacak
CariKartID
```

Recommended mapping:

| Veresiye 5 | Cari |
| --- | --- |
| `ID` | `Transaction.legacy_id` |
| `CariKartID` | Current `customer_id` through legacy-ID mapping |
| `Tarih` | `Transaction.transaction_date` |
| `Saat` | `Transaction.transaction_time` when valid |
| `Aciklama` | `Transaction.description` |
| `Borc` | Positive `amount_kurus` |
| `Alacak` | Negative `amount_kurus` |

`Tur` and legacy `Unvan` may be used as validation/reference fields but are not required as current authoritative fields.

---

# Money Conversion

Legacy monetary values must be converted exactly.

Binary floating-point conversion must not be used.

Conceptually:

```text
Legacy debt:   1500.50 TL → +150050 kuruş
Legacy credit:  300.00 TL →  -30000 kuruş
```

Rules:

- `Borc > 0` and `Alacak == 0` → positive movement
- `Alacak > 0` and `Borc == 0` → negative movement
- Both zero → invalid/non-financial row requiring review
- Both non-zero → ambiguous row requiring review

Unexpected rows must never be silently converted using a guessed rule.

---

# Customer Relationship Mapping

New Cari primary keys do not need to match legacy primary keys.

The importer builds an explicit mapping:

```text
legacy CariKart.ID
        ↓
new Customer.id
```

Then every `Data.CariKartID` is resolved through that mapping.

Example:

```text
Legacy customer ID: 42
New Cari customer ID: 107
```

A legacy transaction containing:

```text
CariKartID = 42
```

must be stored with:

```text
customer_id = 107
legacy_id = original Data.ID
```

The importer must never assume that the new primary key equals the old key.

---

# Legacy ID Preservation

`legacy_id` is stored for imported customers and transactions.

It is used for:

- Troubleshooting
- Side-by-side comparison
- Reconciliation
- Duplicate migration detection

New records created directly in Cari normally have:

```text
legacy_id = NULL
```

Legacy IDs are reference metadata only.

`Customer.registered_on` preserves the legacy customer business/registration date when available. It must not be replaced by the Cari `created_at` timestamp.

`Transaction.transaction_time` preserves the legacy `Data.Saat` value when valid. The field remains nullable because time data may be absent or invalid in legacy records.

Animal records are a Cari Version 1 feature and have no known direct Veresiye 5 source table, so Version 1 does not require `Animal.legacy_id`.

---

# Financial History Preservation

Every valid historical financial movement should be imported.

Descriptions and business dates should remain unchanged except for required encoding/normalization that does not alter meaning.

Payments are not allocated to specific debts.

The new ledger remains:

```text
positive amount = debt
negative amount = payment
```

---

# Balance Calculation

Legacy customer `Bakiye` is not copied as the current balance.

After movements are imported:

```text
Cari balance = SUM(active imported amount_kurus)
```

Legacy `Borc`, `Alacak`, and `Bakiye` summary fields may then be compared with the new calculated values.

The new transaction history remains authoritative.

---

# Reconciliation

Migration must verify aggregate and relationship integrity.

At minimum, compare where source data permits:

- Number of customers
- Number of financial movements
- Total legacy debt
- Total legacy payments/credit
- New total positive movements
- New total negative movements
- Per-customer calculated balances for representative/all feasible customers
- Broken `CariKartID` references
- Invalid dates
- Invalid monetary rows

Critical discrepancies in imported movement counts, mappings, or totals should prevent finalization.

A difference between a legacy stored summary balance and a correctly reconstructed transaction balance may be reported as a warning because the legacy summary itself may be stale or inconsistent.

Warnings must never be silently hidden.

---

# Import Transaction and Rollback

The current-database write portion of migration should be atomic whenever practical.

Conceptually:

```text
Begin destination transaction
        ↓
Insert customers
        ↓
Build legacy-to-current customer map
        ↓
Insert transactions
        ↓
Run critical reconciliation
        ↓
Commit
```

If a critical failure occurs before commit:

```text
Rollback
```

No partial production migration remains.

Long operations may use chunked implementation internally only if the same all-or-nothing safety can still be guaranteed or if a staging database is used and atomically promoted after validation.

---

# Import Report

After analysis and migration, Cari should produce a clear report containing:

- Source filename
- Source fingerprint/checksum when practical
- Import timestamp
- Customer count
- Transaction count
- Total debt
- Total payments
- Warning count
- Error count
- Reconciliation result
- Cari/database version

The normal report should avoid unnecessary customer personal data.

Detailed problem rows may be shown only when required for manual correction.

---

# Import Logging

Technical logs may contain:

- Migration stage
- Counts
- Legacy numeric IDs
- Structural warnings
- Exceptions

Logs should avoid copying customer names, phone numbers, addresses, notes, or full financial histories unless absolutely necessary for a temporary controlled diagnostic.

---

# Performance and UI Responsiveness

Legacy migration may take long enough to block the UI.

The operation should therefore provide progress and, when necessary, run through an appropriate worker mechanism.

Database sessions/connections must follow the threading rules in `09-architecture.md`.

The UI must never allow the user to assume migration completed before final reconciliation/commit succeeds.

---

# Migration Rehearsal

Before production transition:

1. Make a copy of the legacy backup.
2. Import into a test/new Cari database.
3. Compare aggregate counts and totals.
4. Compare representative customers side by side.
5. Inspect old and recent transaction history.
6. Test generated account statements.
7. Create and restore a Cari backup.
8. Only then perform the production migration.

The original legacy program/data should remain available read-only during the transition period.

---

# Unsupported / Invalid Data

The importer must not guess when source data is ambiguous.

Examples requiring warning or failure include:

- Missing customer name
- Broken `CariKartID`
- Invalid date
- Invalid amount
- Both `Borc` and `Alacak` non-zero
- Zero-value financial row
- Missing required legacy table
- Unexpected schema version/shape

The final migration policy for each encountered real-world anomaly should be documented after inspecting representative legacy data.

---

# Future Improvements

Outside Version 1:

- General merge import into non-empty databases
- CSV import
- Excel import
- Selective customer import
- Selective date-range import
- Interactive duplicate-merging tools
- Import from other accounting software

These features should not complicate the one-time Veresiye 5 migration.

---

# Import Principles

1. Never modify the legacy source.
2. Preserve valid historical financial movements.
3. Preserve useful legacy IDs as references.
4. Rebuild current primary-key relationships explicitly.
5. Store money as signed integer kuruş.
6. Recalculate current balances from movement history.
7. Reconcile counts and totals before trusting migration.
8. Roll back critical failures.
9. Do not silently guess ambiguous legacy data.
10. Keep Version 1 migration deterministic by using an empty destination database.

Migration is successful only when the new data can be reconciled against the legacy history closely enough to justify replacing the old application.
