# Coding Style and Development Rules

## Purpose

This document defines the coding conventions and development rules for the Hesiva application.

Its purpose is not to enforce personal formatting preferences.

Its purpose is to ensure that code written at different times, by different contributors, or with AI-assisted development remains:

- Consistent
- Readable
- Predictable
- Testable
- Maintainable
- Safe for business data

These rules apply to all production Python code unless a documented technical reason requires an exception.

The architecture defined in `09-architecture.md` takes priority over stylistic convenience.

---

# General Philosophy

Hesiva is a long-lived desktop business application.

Code should be optimized primarily for:

1. Correctness
2. Data integrity
3. Readability
4. Maintainability
5. Simplicity
6. Performance

Clever code is not preferred over understandable code.

A solution that is slightly longer but immediately understandable is generally preferred over a short solution that requires additional reasoning.

Avoid premature abstraction.

Avoid premature optimization.

Avoid introducing patterns only because they are popular.

Every abstraction should solve an actual problem in the application.

---

# Language

Production code is written in English.

This includes:

- File names
- Class names
- Function names
- Variable names
- Database column names
- Log messages intended for developers
- Comments
- Docstrings
- Test names

The graphical user interface is primarily Turkish.

User-facing messages, labels, dialogs, validation messages, menu items, and report text should therefore normally be written in Turkish.

Example:

```python
class CustomerService:
    ...
```

User-facing text:

```python
message = "Müşteri adı boş bırakılamaz."
```

Do not use Turkish identifiers such as:

```python
musteri_ekle()
borc_hesapla()
```

Use:

```python
create_customer()
calculate_balance()
```

---

# Python Version

Version 1 targets Python 3.13 or a project-approved newer compatible version.

The minimum supported Python version must be defined in `pyproject.toml`.

Code must not rely on behavior that is unsupported by the declared minimum Python version.

---

# Formatting and Linting

Ruff is the official formatter and linter.

Do not use multiple competing formatters.

In particular, the project should not require both Black and Ruff Formatter.

Formatting should be automated.

Developers should not manually attempt to align code using spaces.

Example:

Incorrect:

```python
name       = customer.name
phone      = customer.phone
created_at = customer.created_at
```

Correct:

```python
name = customer.name
phone = customer.phone
created_at = customer.created_at
```

The canonical formatting configuration must live in `pyproject.toml`.

Recommended maximum line length:

```text
100 characters
```

The formatter remains authoritative.

---

# Imports

Imports should be grouped in this order:

1. Python standard library
2. Third-party libraries
3. Hesiva application imports

Example:

```python
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QWidget
from sqlalchemy.orm import Session

from hesiva.models.customer import Customer
from hesiva.services.customer_service import CustomerService
```

Wildcard imports are forbidden.

Do not use:

```python
from module import *
```

Import only what is required.

Circular imports should be treated as an architectural problem rather than worked around with excessive local imports.

Local imports inside functions are acceptable only when there is a concrete reason.

---

# Naming Conventions

Use `snake_case` for:

- Functions
- Methods
- Variables
- Module names
- File names
- Database table names
- Database column names

Examples:

```python
create_customer()
customer_id
transaction_date
customer_repository.py
```

Use `PascalCase` for:

- Classes
- Exceptions
- Qt widgets implemented as classes

Examples:

```python
CustomerService
TransactionRepository
MainWindow
ImportValidationError
```

Use `UPPER_SNAKE_CASE` for true constants.

Example:

```python
DEFAULT_BACKUP_RETENTION_DAYS = 7
```

Do not use uppercase constants for values that are actually configurable application settings.

---

# Names Should Describe Intent

Prefer descriptive names.

Avoid names such as:

```python
data
info
thing
obj
tmp
value2
x
res
```

when a meaningful name can be used.

Prefer:

```python
customer
transaction
outstanding_balance
backup_path
legacy_customer_id
```

Short names are acceptable for very limited and obvious scopes.

Example:

```python
for row in rows:
    ...
```

Names should describe what something represents, not how it is implemented.

---

# Functions

Functions should have one clear responsibility.

A function should normally perform one conceptual operation.

Avoid functions that:

- Validate input
- Modify the database
- Generate a report
- Display a dialog
- Create a backup

all at once.

Instead, responsibilities should be separated according to the architecture.

Prefer early returns when they improve clarity.

Example:

```python
def get_customer(customer_id: int) -> Customer:
    customer = repository.find_by_id(customer_id)

    if customer is None:
        raise CustomerNotFoundError(customer_id)

    return customer
```

rather than deeply nested conditions.

Artificial numeric limits such as "every function must be fewer than 20 lines" are not enforced.

A long function should be refactored when it contains multiple responsibilities or becomes difficult to understand.

Do not split simple logic into many tiny functions only to reduce line count.

---

# Classes

A class should represent one clear responsibility.

Classes should not become general-purpose containers for unrelated functionality.

Avoid classes named:

```text
Manager
Helper
Utils
Common
EverythingService
```

unless their responsibility is genuinely specific and well-defined.

Prefer:

```text
BackupService
ReminderService
TransactionRepository
Veresiye5Reader
```

Composition is generally preferred over deep inheritance hierarchies.

Application business logic should not depend on complicated class inheritance.

---

# Type Hints

Production Python code should use type hints.

Public functions and methods must have parameter and return type annotations unless there is a strong technical reason not to.

Example:

```python
def calculate_balance(customer_id: int) -> int:
    ...
```

Avoid:

```python
def calculate_balance(customer_id):
    ...
```

Use modern Python type syntax.

Prefer:

```python
Customer | None
list[Customer]
dict[int, int]
```

instead of older equivalents when supported by the project's minimum Python version.

Avoid using `Any` unless the value genuinely cannot be typed more specifically.

`Any` must not be used simply to silence type problems.

---

# Monetary Values

Money must never be represented using binary floating-point values for authoritative financial data.

Stored financial values use signed integer minor units.

For Turkish Lira:

```text
1 TL = 100 kuruş
```

Example:

```python
amount_kurus = 150000
```

represents:

```text
1500.00 TL
```

Financial direction is encoded by the sign:

```text
amount_kurus > 0  → debt/charge
amount_kurus < 0  → payment/credit
amount_kurus == 0 → invalid transaction
```

The normal payment UI accepts a positive magnitude and the service layer converts it to a negative stored amount exactly once.

Do not add a second persistent `transaction_type` field merely to duplicate the sign unless a future reviewed requirement genuinely needs it.

Conversion from user-entered decimal text to integer kuruş must occur in a dedicated, tested conversion function.

Formatting integer kuruş into Turkish Lira must also use a dedicated helper.

Do not scatter money conversion/sign logic across UI widgets.

Balance presentation must not change the signed domain value. A positive balance is displayed as
**Borç**, zero is neutral, and a negative balance is formatted from its absolute magnitude as
**Fazla Ödeme**. **Alacak** is reserved for historically accurate legacy-field references, not the
normal negative-balance UI label.

# Dates and Times

Use Python standard date/time types internally.

Prefer:

```python
datetime.date
datetime.datetime
```

instead of passing dates around as arbitrary strings.

The UI may display:

```text
07.08.2026
```

but internal application logic should not rely on that presentation format.

Dates received from legacy systems must be parsed explicitly.

Do not make assumptions about ambiguous date formats during import.

Database timestamps should follow one consistent application-wide convention.

---

# Database Access

The UI must never execute SQL directly.

Services must not contain raw SQL.

Database access belongs inside repositories and database infrastructure.

Conceptually:

```text
UI
↓
Service
↓
Repository
↓
SQLAlchemy
↓
SQLite
```

Incorrect:

```python
class MainWindow:
    def load_customers(self):
        session.execute(...)
```

Correct:

```python
class MainWindow:
    def load_customers(self):
        customers = self.customer_service.list_customers()
```

---

# SQLAlchemy

SQLAlchemy is the official persistence toolkit for Version 1.

Use SQLAlchemy 2.x style APIs.

Deprecated legacy SQLAlchemy patterns must not be introduced.

Database sessions should have clearly defined lifetimes.

Do not keep uncontrolled global sessions alive for the entire process.

A repository should receive or obtain a session using the project's established session management strategy.

Transactions must be explicit for operations where multiple database writes form one logical action.

---

# Database Transactions

Any logical operation that requires multiple related writes must be atomic.

Example:

```text
Import customer
↓
Import transactions
↓
Update references
```

If a critical step fails, the operation should roll back.

Never allow half-completed business operations to remain silently in the database.

Do not call `commit()` repeatedly inside low-level repository methods without considering the complete business transaction.

Transaction boundaries should normally be coordinated by the service or application-level operation.

---

# Foreign Keys

SQLite foreign key enforcement must be enabled.

Relationships must not rely purely on application convention when the database can enforce them safely.

Important historical financial information must not be accidentally deleted through uncontrolled cascade behavior.

Cascade rules must be intentional and reviewed.

---

# Balance Rules

Customer balance is derived from non-voided signed transaction history.

Conceptually:

```text
balance_kurus = SUM(amount_kurus)
```

Do not create application logic that treats a stored customer balance field as authoritative.

Positive amounts represent debt.

Negative amounts represent payment/customer credit.

Voided transactions are excluded.

All balance calculations should use the same centralized business rule.

Do not independently implement balance formulas in:

- Main window
- Reports
- Customer dialogs
- Import code

If multiple components require a calculation, the rule belongs in a shared service or repository query with clearly defined semantics.

# Historical Financial Data

Historical financial records require special care.

Transactions must not normally be physically deleted.

Version 1 corrects an incorrect financial record by voiding it and creating a new transaction when
required. Existing transaction business fields are not directly edited.

Voided records remain stored but no longer affect active balances, last activity, or normal reports.

UI wording may use a familiar destructive label only if the resulting confirmation clearly communicates what will happen; the implementation must still follow the data-preservation policy.

Voiding a historical record or creating its correction must not silently affect unrelated customers
or relationships.

# Validation

Validation should occur as close as practical to the business logic.

The UI may perform basic presentation validation such as detecting an obviously empty field.

Authoritative validation belongs in services.

Example:

UI:

```text
Amount field is empty.
```

Service:

```text
Amount must represent a valid positive debt/payment amount.
Customer must exist.
Selected animal must belong to the selected customer.
```

Never rely only on UI validation.

Imported data and automated operations do not necessarily pass through the same UI.

---

# Exceptions

Use exceptions for exceptional failure conditions.

Create application-specific exceptions when they improve clarity.

Examples:

```python
class CustomerNotFoundError(Exception):
    pass


class InvalidTransactionError(Exception):
    pass


class BackupVerificationError(Exception):
    pass
```

Do not use broad exception handling such as:

```python
try:
    ...
except Exception:
    pass
```

Never silently swallow an exception.

If a broad exception must be caught at an application boundary, it must be:

- Logged appropriately
- Converted into a safe user-facing error
- Handled without corrupting data

Do not use exceptions as normal branching logic when a simple conditional is clearer.

---

# User-Facing Errors

Raw technical exceptions should not normally be shown directly to users.

Incorrect:

```text
sqlalchemy.exc.IntegrityError:
UNIQUE constraint failed...
```

Preferred:

```text
Bu kayıt kaydedilemedi. Aynı kayıt zaten mevcut olabilir.
```

Technical details belong in logs where appropriate.

User messages should explain:

- What failed
- Whether data was saved
- What the user can do next

Messages should not falsely claim success when an operation has only partially completed.

---

# Logging

Use Python's standard `logging` module.

Do not use `print()` for production diagnostics.

Temporary development `print()` calls must be removed before merging completed work.

Recommended log levels:

```text
DEBUG
Detailed development diagnostics

INFO
Normal major application events

WARNING
Unexpected but recoverable conditions

ERROR
Failed operations

CRITICAL
Failures that may prevent safe application operation
```

Do not log:

- Plain-text passwords
- Password hashes
- Full customer histories
- Complete private customer notes
- Unnecessary personal information

Logs should contain enough context for troubleshooting without becoming a secondary copy of business data.

---

# Comments

Comments should explain why something exists, not repeat what the code already says.

Bad:

```python
# Add one to count
count += 1
```

Useful:

```python
# Legacy customer IDs are preserved only for import verification.
# They are never used as current application primary keys.
legacy_id = row["ID"]
```

Do not keep commented-out old code.

Git already preserves history.

Delete obsolete code instead.

---

# Docstrings

Docstrings are encouraged for:

- Public services
- Non-obvious repository operations
- Import readers
- Backup logic
- Complex business rules
- Public reusable helpers

Trivial private methods do not require a docstring when their purpose is already obvious from their name and types.

Prefer concise docstrings.

Example:

```python
def calculate_balance(customer_id: int) -> int:
    """Return the customer's outstanding balance in kuruş."""
```

Do not write multi-paragraph docstrings that merely restate straightforward implementation details.

---

# TODO Comments

Avoid vague TODO comments.

Bad:

```python
# TODO fix later
```

Better:

```python
# TODO(#42): Add a regression test before changing this parser.
```

Important unfinished work should normally be tracked through the project's issue/task system rather than forgotten inside source code.

---

# Constants and Magic Values

Avoid unexplained magic values.

Bad:

```python
if attempts > 5:
    ...
```

Prefer:

```python
MAX_LOGIN_ATTEMPTS = 5
```

or use application configuration when appropriate.

However, do not create constants for every obvious literal.

Example:

```python
balance = amount * 100
```

may still benefit from a named money conversion helper rather than:

```python
KURUS_PER_LIRA = 100
```

being manually used throughout the application.

---

# Global State

Avoid mutable global state.

Do not create globally accessible objects such as:

```python
GLOBAL_SESSION
CURRENT_CUSTOMER
GLOBAL_DATABASE
```

Application dependencies should be passed explicitly.

For example:

```python
class CustomerService:
    def __init__(self, repository: CustomerRepository) -> None:
        self.repository = repository
```

Explicit dependencies make behavior easier to understand and test.

---

# Dependency Injection

Hesiva uses simple constructor-based dependency injection.

A dependency injection framework is not required.

Example:

```python
customer_repository = CustomerRepository(session_factory)
customer_service = CustomerService(customer_repository)
main_window = MainWindow(customer_service)
```

Do not introduce a complex dependency injection container unless a concrete need appears.

---

# PySide6 UI Rules

Qt widgets should focus on presentation and user interaction.

A dialog may:

- Read text from fields
- Call a service
- Display validation errors
- Close after a successful operation

A dialog should not:

- Execute SQL
- Calculate balances independently
- Create backup archives
- Parse old databases
- Hash passwords

Signal and slot connections should remain readable.

Avoid extremely large UI classes containing every screen and business behavior in the application.

Reusable visual components may be extracted into widgets when genuine reuse exists.

---

# Qt Object Ownership

Follow Qt's parent-child ownership model.

Where possible, widgets should receive an appropriate parent.

Do not keep unnecessary duplicate references to Qt objects.

Understand whether an object's lifetime is controlled by:

- Python
- Qt parent ownership
- Both

Before introducing manual cleanup logic.

---

# UI Text

User-facing strings should be clear Turkish.

Avoid overly technical wording.

Prefer:

```text
Yedek oluşturulamadı.
```

over:

```text
SQLite backup API failure.
```

Technical details may be available in logs.

Terminology should remain consistent throughout the application.

For example, do not randomly alternate between:

```text
Hesiva
Müşteri
Firma
Hesap Sahibi
```

for the same concept unless the UI specification explicitly requires it.

---

# Keyboard Navigation

The application is intended for fast desktop use.

Dialogs should support logical keyboard navigation.

Tab order must follow visible form order.

Important dialogs should support appropriate keyboard actions such as:

```text
Enter
Save or confirm when safe

Escape
Cancel or close
```

Keyboard shortcuts must not trigger destructive operations accidentally.

---

# Threading

Do not introduce threading for normal short operations.

Use background workers only for operations that may noticeably block the interface.

Examples:

- Large legacy import
- Backup
- Restore
- Large report generation

Qt UI objects must only be modified from the appropriate UI thread.

SQLite/SQLAlchemy sessions must not be unsafely shared across worker threads.

A worker should obtain its own appropriate database session.

---

# Import Code

Legacy import code must remain isolated.

Legacy table names such as:

```text
CariKart
Data
ATemp
```

must not leak throughout the current application.

Only the Veresiye importer should understand legacy schema details.

Legacy source databases must be opened read-only.

Import code must never modify the original source database.

Import mapping should be explicit and testable.

Do not rely on column positions when named columns are available.

---

# Legacy IDs

Imported legacy identifiers may be stored as optional reference values.

They are intended for:

- Import verification
- Troubleshooting
- Duplicate import detection
- Comparing old and new records

They must not become the primary identity system of the new application.

Newly created records normally have:

```text
legacy_id = NULL
```

Never assume that a legacy ID is globally unique across unrelated legacy databases unless this has been explicitly verified.

---

# Backup Code

Backup operations must use SQLite-safe backup mechanisms.

Do not create a database backup using an uncontrolled raw file copy while the database may be active.

Backup success must only be reported after verification.

Backup code must clearly distinguish:

- Source database
- Temporary snapshot
- Final backup archive
- Restore destination

A backup operation must never overwrite the live database.

---

# File System Operations

Use `pathlib.Path` for filesystem paths.

Prefer:

```python
from pathlib import Path
```

instead of manually concatenating path strings.

Incorrect:

```python
path = base + "/" + filename
```

Correct:

```python
path = base / filename
```

Do not assume Linux path separators because Windows is a secondary supported platform.

---

# Configuration Paths

Do not hard-code user-specific absolute paths.

Incorrect:

```python
Path("/home/kayra/hesiva/data.db")
```

Application directories must be resolved using the project's platform-aware path utilities.

Tests must use temporary directories rather than production paths.

---

# File Encoding

Source code and project text files use UTF-8.

Do not depend on the operating system's implicit default encoding for files that contain application data.

Specify encoding where appropriate.

Example:

```python
path.read_text(encoding="utf-8")
```

---

# Security Rules

Never store passwords in plain text.

Never log passwords.

Never invent custom cryptographic algorithms.

Use approved, maintained cryptographic libraries.

Password verification should remain behind `AuthService`.

Do not build SQL queries through untrusted string concatenation.

Incorrect:

```python
query = f"SELECT * FROM customers WHERE name = '{name}'"
```

Use SQLAlchemy expressions or properly bound parameters.

---

# External Dependencies

Dependencies should be added conservatively.

Before adding a library, determine whether:

- It solves a real problem
- It is actively maintained
- It supports Linux and Windows
- It is appropriate for the target hardware
- The Python standard library or an existing dependency already solves the problem

Avoid adding large dependencies for trivial functionality.

Every production dependency must be declared in `pyproject.toml`.

Unused dependencies must be removed.

---

# Performance

Correctness takes priority over micro-optimization.

However, code should avoid obviously inefficient behavior.

Examples of behavior to avoid:

- Loading every transaction in the database when only one customer is needed
- Executing one database query per row when a single query can retrieve the data
- Recalculating identical expensive reports repeatedly without reason
- Blocking the UI with a long import operation

Database indexes should be introduced based on actual query requirements.

Likely indexed fields include:

- Customer names used for search
- Transaction customer IDs
- Transaction dates
- Reminder dates
- Legacy identifiers where duplicate detection requires them

Indexes should be defined deliberately rather than added everywhere.

---

# Search Behavior

Search implementation should be predictable and efficient.

Search normalization should live outside individual UI widgets when possible.

Do not build separate customer-search algorithms in multiple screens.

If normalization rules such as Turkish case handling are required, they should be centralized and tested.

---

# Testing Requirements

New business logic should normally be accompanied by tests.

A feature is not considered complete simply because the UI appears to work manually.

Critical logic requiring automated coverage includes:

- Balance calculations
- Debt creation
- Payment creation
- Money parsing
- Customer relationships
- Animal ownership rules
- Reminder due-date logic
- Import mapping
- Import rollback
- Backup creation
- Backup verification
- Database migrations

Detailed testing policy is defined in `11-testing.md`.

---

# Test Code Style

Tests should be readable descriptions of expected behavior.

Prefer descriptive test names.

Example:

```python
def test_payment_reduces_customer_balance() -> None:
    ...
```

rather than:

```python
def test_transaction_4() -> None:
    ...
```

A test should make it obvious:

- What state is created
- What operation occurs
- What result is expected

Tests must never use the real production database.

---

# Database Migrations

Schema changes must use Alembic migrations after the initial migration system exists.

Do not modify a production schema manually and assume installed databases will somehow update.

A schema change should include:

1. Model update
2. Migration
3. Migration test or verification
4. Documentation update if behavior changes

Existing user data must be preserved.

---

# Compatibility

Linux is the primary platform.

Windows is secondary.

Do not use operating-system-specific APIs directly inside general business logic.

Platform-specific behavior should be isolated behind a small dedicated abstraction when necessary.

Code should not assume:

- A specific home directory
- A specific desktop environment
- A specific Windows drive letter
- A specific Linux distribution

---

# Resource Usage

Hesiva targets older hardware.

Avoid unnecessarily heavy background processes.

Avoid polling loops when event-based behavior is available.

Avoid loading large datasets into memory without need.

Avoid unnecessary animations and expensive visual effects.

Application startup should remain fast.

---

# Code Duplication

Small amounts of clear duplication are preferable to a premature abstraction that makes code difficult to understand.

However, important business rules must not be duplicated.

Especially avoid duplicated implementations of:

- Balance calculations
- Money conversion
- Date parsing
- Backup verification
- Import normalization
- Authentication behavior

Extract shared code when the duplicated behavior represents the same concept.

---

# Refactoring

Refactoring must preserve observable behavior unless behavior change is explicitly part of the task.

Before significant refactoring:

- Relevant tests should exist
- Current behavior should be understood
- Data compatibility should be considered

Do not combine large unrelated refactors with feature implementation unless necessary.

Small, focused changes are easier to review and recover from.

---

# AI-Assisted Development

AI-generated code is treated exactly like human-written code.

Generated code is not accepted merely because it runs.

Before accepting AI-generated changes, verify:

- Architecture boundaries are respected
- Existing behavior is preserved
- Tests pass
- New behavior is tested
- No unnecessary dependencies were introduced
- No duplicate implementations were created
- No sensitive data is logged
- Database operations are safe
- Error handling is appropriate
- Code remains understandable

AI tools must follow the repository documentation rather than inventing new architecture.

If documentation and an implementation request conflict, the conflict should be resolved before implementation rather than silently choosing one interpretation.

AI tools should not make unrelated changes while implementing a focused task.

---

# Scope Discipline

When implementing a task, only implement the requested scope.

For example, a task to add customer creation should not independently introduce:

- Inventory
- Cloud synchronization
- A new theme framework
- A different ORM
- A plugin system

Ideas outside the current task should be documented separately rather than implemented opportunistically.

Version 1 scope is defined by the project documentation.

---

# No Silent Architectural Changes

Changes to major architectural decisions require explicit review.

Examples include:

- Replacing SQLite
- Replacing PySide6
- Replacing SQLAlchemy
- Changing the financial transaction model
- Storing balances directly
- Introducing cloud services
- Introducing a permanent server component
- Changing backup format
- Adding database encryption

An implementation task must not silently change these decisions.

---

# Git-Friendly Changes

Changes should be small and focused enough to review.

Avoid reformatting unrelated files as part of a feature.

Avoid renaming unrelated modules without need.

Generated files, temporary files, local databases, logs, build output, and IDE state must not be committed unless explicitly required.

The `.gitignore` file should cover development artifacts.

---

# Completed Code

Code is considered complete when:

- It follows the documented architecture
- It follows this coding style
- It handles relevant errors
- It preserves data integrity
- Required tests exist
- Tests pass
- Ruff checks pass
- Ruff formatting passes
- No debug code remains
- No unrelated functionality was changed
- Relevant documentation is still accurate

"Works on my machine" is not sufficient completion criteria.

---

# Review Checklist

Before accepting a change, verify:

- Is the code in the correct architectural layer?
- Are names clear?
- Are types defined?
- Is financial data represented safely?
- Is database access isolated?
- Is the operation transactional where required?
- Can an error leave partial data behind?
- Are user-facing errors understandable?
- Are sensitive values absent from logs?
- Is the code unnecessarily complicated?
- Has an existing helper or service been duplicated?
- Are relevant tests included?
- Does the change work on the supported architecture?
- Did the change introduce anything outside the requested scope?

If any answer reveals uncertainty about data integrity, the change should not be considered complete until the uncertainty is resolved.

---

# Summary

Hesiva code should be:

```text
Simple
Explicit
Typed
Layered
Tested
Data-safe
```

The preferred dependency direction remains:

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

The project deliberately avoids:

- Business logic inside UI widgets
- SQL scattered throughout the application
- Floating-point financial storage
- Uncontrolled global state
- Silent exception handling
- Premature abstractions
- Unnecessary dependencies
- Raw copying of active SQLite databases
- Physical deletion of important financial history
- Architecture invented independently by individual implementation tasks

The most important rule is:

> Code should make the application's behavior easier to understand, not harder.

Hesiva is expected to store business data for many years. Reliability and clarity therefore have greater value than clever implementation techniques.
