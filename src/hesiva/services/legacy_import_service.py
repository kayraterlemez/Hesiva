from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from hesiva.importers.veresiye5_reader import (
    LegacyImportPlan,
    LegacySourceError,
    read_legacy_import_plan,
)
from hesiva.models.customer import Customer
from hesiva.read_models import LegacyImportPreflight, LegacyImportResult
from hesiva.repositories.legacy_import_repository import LegacyImportRepository
from hesiva.services.exceptions import (
    LegacyImportDestinationNotEmptyError,
    LegacyImportError,
    LegacyImportSourceError,
    LegacyImportVerificationError,
)


class LegacyImportService:
    """Coordinate strict source analysis and one atomic destination import."""

    def __init__(self, session: Session, repository: LegacyImportRepository) -> None:
        self._session = session
        self._repository = repository

    def preflight(self, source_path: Path) -> LegacyImportPreflight:
        plan = self._read_plan(source_path)
        self._ensure_empty_destination()
        return plan.preflight

    def is_destination_empty(self) -> bool:
        """Return whether the business database has no import-relevant records."""
        return self._repository.business_record_counts().is_empty

    def import_source(
        self,
        source_path: Path,
        *,
        expected_source_sha256: str,
        progress: Callable[[str], None] | None = None,
    ) -> LegacyImportResult:
        plan = self._read_plan(source_path)
        if plan.source_sha256 != expected_source_sha256:
            raise LegacyImportSourceError(
                "Seçilen kaynak analizden sonra değişti. Lütfen yeniden analiz edin."
            )

        try:
            self._ensure_empty_destination()
            if progress is not None:
                progress("customers")
            customer_id_by_legacy_id = self._insert_customers(plan)
            if progress is not None:
                progress("transactions")
            self._insert_transactions(plan, customer_id_by_legacy_id)
            if progress is not None:
                progress("verification")
            self._verify_destination(plan)
            self._session.commit()
        except LegacyImportError:
            self._session.rollback()
            raise
        except Exception as error:
            self._session.rollback()
            raise LegacyImportError(
                "Veriler güvenli şekilde içe aktarılamadı; hedef veritabanı değiştirilmedi."
            ) from error

        preflight = plan.preflight
        return LegacyImportResult(
            source_customer_count=preflight.source_customer_count,
            skipped_placeholder_customers=preflight.skipped_placeholder_customers,
            imported_customer_count=preflight.eligible_customer_count,
            source_data_count=preflight.source_data_count,
            skipped_zero_movement_transactions=(preflight.skipped_zero_movement_transactions),
            imported_transaction_count=preflight.eligible_transaction_count,
            total_debt_kurus=preflight.total_debt_kurus,
            total_payment_kurus=preflight.total_payment_kurus,
            signed_net_kurus=preflight.signed_net_kurus,
            stored_summary_compared_customers=(preflight.stored_summary_compared_customers),
            stored_summary_matching_customers=(preflight.stored_summary_matching_customers),
            stored_summary_mismatching_customers=(preflight.stored_summary_mismatching_customers),
            warnings=preflight.warnings,
        )

    def _read_plan(self, source_path: Path) -> LegacyImportPlan:
        try:
            return read_legacy_import_plan(source_path)
        except LegacySourceError as error:
            raise LegacyImportSourceError(
                "Seçilen Veresiye 5 kaynağı desteklenmiyor veya güvenli şekilde doğrulanamadı."
            ) from error

    def _ensure_empty_destination(self) -> None:
        if not self._repository.business_record_counts().is_empty:
            raise LegacyImportDestinationNotEmptyError(
                "İçe aktarma yalnızca boş bir Hesiva iş veritabanında yapılabilir."
            )

    def _insert_customers(self, plan: LegacyImportPlan) -> dict[int, int]:
        customers = [
            Customer(
                legacy_id=record.legacy_id,
                registered_on=record.registered_on,
                full_name=record.full_name,
                phone=record.phone,
                address=record.address,
                notes=record.notes,
            )
            for record in plan.customers
        ]
        mapping = self._repository.add_customers(customers)
        if len(mapping) != len(plan.customers):
            raise LegacyImportVerificationError("Müşteri kimlik eşlemesi doğrulanamadı.")
        return mapping

    def _insert_transactions(
        self,
        plan: LegacyImportPlan,
        customer_id_by_legacy_id: dict[int, int],
    ) -> None:
        rows = [
            {
                "customer_id": customer_id_by_legacy_id[record.customer_legacy_id],
                "animal_id": None,
                "legacy_id": record.legacy_id,
                "transaction_date": record.transaction_date,
                "transaction_time": record.transaction_time,
                "description": record.description,
                "amount_kurus": record.amount_kurus,
                "note": None,
                "voided_at": None,
                "void_reason": None,
            }
            for record in plan.transactions
        ]
        self._repository.add_transactions(rows)

    def _verify_destination(self, plan: LegacyImportPlan) -> None:
        snapshot = self._repository.destination_snapshot()
        expected = plan.preflight
        if (
            snapshot.customer_count != expected.eligible_customer_count
            or snapshot.transaction_count != expected.eligible_transaction_count
            or snapshot.distinct_customer_legacy_ids != expected.eligible_customer_count
            or snapshot.distinct_transaction_legacy_ids != expected.eligible_transaction_count
            or snapshot.null_customer_legacy_ids
            or snapshot.null_transaction_legacy_ids
            or snapshot.zero_transaction_count
            or snapshot.foreign_key_violation_count
            or snapshot.debt_kurus != expected.total_debt_kurus
            or snapshot.payment_kurus != expected.total_payment_kurus
            or snapshot.signed_net_kurus != expected.signed_net_kurus
        ):
            raise LegacyImportVerificationError(
                "İçe aktarılan kayıtların genel doğrulaması başarısız oldu."
            )
        expected_per_customer = {
            value.customer_legacy_id: (
                value.debt_kurus,
                value.payment_kurus,
                value.signed_net_kurus,
            )
            for value in plan.per_customer
        }
        actual_per_customer = {
            value.customer_legacy_id: (
                value.debt_kurus,
                value.payment_kurus,
                value.signed_net_kurus,
            )
            for value in snapshot.per_customer
        }
        if actual_per_customer != expected_per_customer:
            raise LegacyImportVerificationError(
                "İçe aktarılan müşteri hesaplarının doğrulaması başarısız oldu."
            )
