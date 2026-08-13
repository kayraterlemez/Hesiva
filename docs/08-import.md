# Import System

## Purpose

The import system migrates the existing Veresiye 5 customer and financial history into Hesiva.

This is a critical Version 1 requirement because Hesiva cannot safely replace the legacy application if years of account history disappear during transition.

The importer must preserve business history while keeping the original legacy source unchanged.

---

# Import Scope

Version 1 supports a one-time Veresiye 5 migration.

Primary user-facing source:

- Veresiye 5 backup (`.exa`)

Validated internal/source database format:

- SQLite database stored with an `.edb` extension
- Direct `.edb` selection is an advanced workflow

Version 1 is not a general CSV/Excel importer.

Additional import formats may be considered later.

---

# Known Legacy Structure

The supported `.exa` source is a custom Veresiye 5 framed container, not a renamed ZIP, 7z, RAR,
gzip, tar, OLE document, or SQLite file. It contains zlib-compressed records, a compressed
`FILE:LIST`, `XEC2` record markers, little-endian length fields, Windows-1254 member paths, and an
eight-byte terminal footer. Hesiva parses this structure deterministically and must consume the
complete container. It does not scan arbitrary bytes for SQLite magic.

The parser rejects malformed/truncated framing, corrupt or unconsumed zlib streams, inconsistent
declared lengths, unknown nonzero flags, unexpected markers, decompressed-size mismatches,
trailing bytes, a missing `Frm1.edb`, or multiple members whose basename is `Frm1.edb`. Chunk count
and recovered database size are source-declared values and are not hard-coded from one backup.
Declared-size digit counts are bounded before integer conversion, so pathological numeric text is
reported as an unsupported EXA source rather than escaping the import error contract.

Recovered `Frm1.edb` is SQLite 3. It is created with private permissions inside a private temporary
directory, validated for SQLite magic, opened with SQLite URI `mode=ro&immutable=1`, and placed in
`query_only` mode. It is never passed through Hesiva startup, Alembic, or migration code.

Advanced direct `.edb` selection accepts a regular, singly linked database only. Symbolic-link
targets are resolved for sidecar checks, while hard-linked database identities are rejected because
another filename could own an unseen WAL/journal containing committed data.

An EXA recovery is not reported as successful until its private extracted database/directory has
been removed. If cleanup fails, Hesiva preserves the primary format/read failure when one exists and
otherwise reports a safe import-source failure rather than silently leaving private data behind.

Known tables include:

```text
CariKart
Data
ATemp
```

The supported V1 schema profile requires these exact columns and declared types:

```text
CariKart:
ID integer primary key, Tarih date, Kod char(25), Unvan char(100), Yetkili char(100),
Gsm char(25), Tel char(25), Fax char(25), Adres char(250), il char(50), ilce char(50),
VergiDaire char(25), VergiNo char(25), EPosta char(100), Web char(100), CLimit Money,
Hesap char(5), CNot text, STarih date, Borc Money, Alacak Money, Bakiye Money

Data:
ID integer primary key, Tarih date, Saat time, Tur char(25), Unvan char(100),
Aciklama char(250), Borc Money, Alacak Money, CariKartID integer

ATemp:
ID integer primary key, TurID integer, Aciklama char(250)
```

For Hesiva migration, the important Version 1 business tables are:

```text
CariKart → customers
Data     → financial movements
```

`ATemp` is required for supported-profile schema recognition but is non-authoritative autocomplete
or description-cache data and is never imported.

The importer must validate actual table/column structure instead of trusting the filename extension alone.

---

# Source Protection

The original `.exa` and `.edb` source files are immutable from Hesiva's point of view.

The importer shall:

- Open SQLite source databases read-only
- Never execute write statements against the legacy source
- Never rename or replace the original source
- Extract archive contents only into controlled temporary locations
- Remove temporary extracted copies when they are no longer required
- Decode legacy source text explicitly without changing Hesiva's normal Unicode storage

The original legacy backup remains available for independent recovery/comparison.

---

# Version 1 Migration Model

Version 1 migration is intended for a new/empty Hesiva business database.

This is deliberate.

Merging a complete historical Veresiye 5 database into an already active Hesiva database introduces complex duplicate and conflict rules that are unnecessary for the initial replacement project.

Therefore:

- Initial migration into an empty Hesiva business database is supported.
- Re-running the same complete migration into a database that already contains imported/active business data is blocked.
- General merge/import into a non-empty production database is outside Version 1.

This keeps migration deterministic and easier to verify.

---

# Import Wizard

The frozen five-stage workflow is:

```text
Kaynak
        ↓
Analiz
        ↓
Onay
        ↓
Aktarım
        ↓
Sonuç
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
- SQLite integrity check succeeds
- Legacy text decodes strictly as Windows-1254/CP1254
- Required dates and optional times use the supported exact formats
- Monetary values have supported runtime types and precision
- Legacy IDs and customer references are structurally valid
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

Version 1 uses this authoritative mapping:

| Veresiye 5 | Hesiva |
| --- | --- |
| `ID` | `Customer.legacy_id` |
| `Unvan` | `Customer.full_name` |
| trimmed `Gsm` | Preferred phone when nonblank |
| trimmed `Tel` | Phone fallback when `Gsm` is blank/NULL |
| trimmed nonblank `Adres`, `ilce`, `il` | Joined in that order with `, ` |
| `CNot` | `Customer.notes` |
| `Tarih` (`YYYY-MM-DD`) | `Customer.registered_on`; NULL/blank becomes `None` |

Unsupported identity fields are not squeezed into notes or other current fields.

## Empty placeholder customer

A nameless `CariKart` row is skipped only when it has no linked `Data` rows, all supported customer
text is blank/NULL, and its relevant stored financial summaries are NULL or zero. It is counted as
`skipped_placeholder_customers`. A nameless row with meaningful data or a linked row blocks the
import. Hesiva never generates an “unknown” or “unnamed” customer.

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

Version 1 uses this authoritative mapping for each eligible financial row:

| Veresiye 5 | Hesiva |
| --- | --- |
| `ID` | `Transaction.legacy_id` |
| `CariKartID` | Current `customer_id` through legacy-ID mapping |
| `Tarih` (`YYYY-MM-DD`) | `Transaction.transaction_date` |
| `Saat` (`HH:MM:SS`) | `Transaction.transaction_time`; NULL/blank becomes `None` |
| trimmed `Aciklama`, then `Tur`, then `Unvan` | First nonblank value becomes `Transaction.description` |
| `Borc` | Positive `amount_kurus` |
| `Alacak` | Negative `amount_kurus` |

If all three description candidates are blank, import is blocked. Imported financial rows have
`animal_id = None` and `note = None`; unsupported source fields are not repurposed.

# Legacy Text and Date/Time Contract

Although the source SQLite header declares UTF-8, the supported Veresiye 5 profile stores legacy
text cells as Windows-1254/CP1254 bytes. The source reader obtains bytes and decodes every relevant
text value explicitly and strictly. Undecodable data blocks import; replacement characters,
`errors="ignore"`, and locale-dependent conversion are forbidden. Destination strings are normal
Python Unicode stored by Hesiva as UTF-8.

Before source rows are materialized into Python, the read-only SQLite connection applies a bounded
`SQLITE_LIMIT_LENGTH`; a separate schema-safe ceiling permits the fixed supported schema to be
validated before the exact legacy text-cell ceiling is applied. Application-owned SQL statement
length and the streamed aggregate legacy-text budget are bounded independently.

Before a validated plan can be imported, every mapped destination customer/transaction text value
must also fit Hesiva's shared 1 MiB UTF-8 persisted-text ceiling. Source-only fields retain their
separate parser resource limits; they do not expand the destination storage contract.

`CariKart.Tarih` and `Data.Tarih` accept only `YYYY-MM-DD`; `Data.Tarih` is required for eligible
financial rows. Nonblank `Data.Saat` accepts only valid `HH:MM:SS`. No missing date/time is replaced
with today, midnight, or the current time.

---

# Money Conversion

Legacy monetary values must be converted exactly.

Binary floating-point conversion must not be used.

Conceptually:

```text
Legacy debt:   1500.50 TL → +150050 kuruş
Legacy credit:  300.00 TL →  -30000 kuruş
```

The supported source runtime types for `Borc` and `Alacak` are SQLite INTEGER, REAL, and NULL. NULL
on the unused side is interpreted as zero for classification. Conversion uses a stable decimal
representation and `Decimal`, requires no more than two meaningful decimal places, and produces
integer kuruş without floating-point accumulation or rounding.

Rules:

- `Borc > 0` and normalized `Alacak == 0` → positive movement
- `Alacak > 0` and normalized `Borc == 0` → negative movement
- Both normalized sides zero → defined non-financial row; skip and count as `skipped_zero_movement_transactions`
- Both non-zero → ambiguous row requiring review
- Either side negative, nonnumeric, nonfinite, or more precise than two decimals → blocking anomaly

Zero rows never become fake one-kuruş transactions, reminders, animals, or notes. Unexpected rows
must never be silently converted using a guessed rule.

---

# Customer Relationship Mapping

New Hesiva primary keys do not need to match legacy primary keys.

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
New Hesiva customer ID: 107
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

New records created directly in Hesiva normally have:

```text
legacy_id = NULL
```

Legacy IDs are reference metadata only.

`Customer.registered_on` preserves the legacy customer business/registration date when available. It must not be replaced by the Hesiva `created_at` timestamp.

`Transaction.transaction_time` preserves a valid legacy `Data.Saat` value. The field remains
nullable because time may be NULL/blank; an invalid nonblank time blocks import.

Animal records are a Hesiva Version 1 feature and have no known direct Veresiye 5 source table, so Version 1 does not require `Animal.legacy_id`.

---

# Financial History Preservation

Every eligible nonzero historical financial movement is imported. Defined zero-movement/non-financial
rows are counted in reconciliation but do not become Hesiva transactions.

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
Hesiva balance = SUM(active imported amount_kurus)
```

Legacy `Borc`, `Alacak`, and `Bakiye` summary fields may then be compared with the new calculated values.

The new transaction history remains authoritative.

Stored `CariKart.Borc`, `CariKart.Alacak`, and `CariKart.Bakiye` are reconciliation-only. A mismatch
is reported as a warning and does not replace transaction-derived truth. `CariKart.STarih` is not
authoritative and is never mapped to **Son İşlem**; Hesiva derives Son İşlem from imported financial
transactions.

---

# Reconciliation

Migration must verify aggregate and relationship integrity.

At minimum, compare where source data permits:

- Total `CariKart` rows, skipped placeholders, and eligible/imported customers
- Total `Data` rows, skipped zero movements, and eligible/imported transactions
- Eligible source debt/payment/net against destination positive/negative/signed totals
- Per-customer eligible debt/payment/net for every imported customer
- Preserved distinct/non-NULL customer and transaction legacy IDs
- Destination zero-transaction and foreign-key checks
- Broken `CariKartID` references
- Invalid dates
- Invalid monetary rows

Critical discrepancies in imported movement counts, mappings, or totals should prevent finalization.

A difference between a legacy stored summary balance and a correctly reconstructed transaction balance may be reported as a warning because the legacy summary itself may be stale or inconsistent.

Warnings must never be silently hidden.

---

# Import Transaction and Rollback

The destination write is one caller-owned transaction.

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

Transactions may be flushed in bounded batches, but no batch commits independently. Verification
runs before the one final commit. Customer insertion, transaction insertion, or verification
failure rolls back every imported row.

---

# Import Report

After analysis and migration, Hesiva should produce a clear report containing:

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
- Hesiva/database version

The normal report should avoid unnecessary customer personal data.

Detailed problem rows may be shown only when required for manual correction.

---

# Import Logging

Technical logs may contain:

- Migration stage
- Counts
- Structural warnings
- Exception categories without source row values

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
2. Import into a test/new Hesiva database.
3. Compare aggregate counts and totals.
4. Compare representative customers side by side.
5. Inspect old and recent transaction history.
6. Test generated account statements.
7. Create and restore a Hesiva backup.
8. Only then perform the production migration.

The original legacy program/data should remain available read-only during the transition period.

---

# Unsupported / Invalid Data

The importer must not guess when source data is ambiguous.

Examples requiring warning or failure include:

- Nameless customer that is not a defined empty placeholder
- Broken `CariKartID`
- Invalid date
- Invalid amount
- Both `Borc` and `Alacak` non-zero
- Missing required legacy table
- Unexpected schema version/shape

Defined empty customer placeholders and zero-movement rows are not anomalies: they are skipped and
counted under their explicit categories.

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
11. Never invent a customer name or nonzero financial movement.

Migration is successful only when the new data can be reconciled against the legacy history closely enough to justify replacing the old application.
