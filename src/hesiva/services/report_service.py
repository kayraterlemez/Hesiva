from datetime import date

from hesiva.read_models import CustomerStatement, MonthlySummary, YearlySummary
from hesiva.repositories.report_repository import ReportRepository
from hesiva.services.exceptions import CustomerNotFoundError, ValidationError


class ReportService:
    """Expose immutable, read-only V1 financial reports."""

    def __init__(self, report_repository: ReportRepository) -> None:
        self._report_repository = report_repository

    def get_customer_statement(
        self,
        customer_id: int,
        *,
        period_start: date,
        period_end: date,
    ) -> CustomerStatement:
        self._validate_date(period_start)
        self._validate_date(period_end)
        if period_start > period_end:
            raise ValidationError("Statement start date cannot be after its end date.")

        statement = self._report_repository.get_customer_statement(
            customer_id,
            period_start=period_start,
            period_end=period_end,
        )
        if statement is None:
            raise CustomerNotFoundError(f"Customer {customer_id} was not found.")
        return statement

    def get_monthly_summary(self, *, year: int, month: int) -> MonthlySummary:
        self._validate_year(year)
        if not 1 <= month <= 12:
            raise ValidationError("Month must be between 1 and 12.")
        period_start = date(year, month, 1)
        period_end = date(year + (month == 12), month % 12 + 1, 1)
        return self._report_repository.get_monthly_summary(
            year=year,
            month=month,
            period_start=period_start,
            period_end=period_end,
        )

    def get_yearly_summary(self, *, year: int) -> YearlySummary:
        self._validate_year(year)
        return self._report_repository.get_yearly_summary(
            year=year,
            period_start=date(year, 1, 1),
            period_end=date(year + 1, 1, 1),
        )

    @staticmethod
    def _validate_date(value: date) -> None:
        if type(value) is not date:
            raise ValidationError("Report dates must be date values.")

    @staticmethod
    def _validate_year(year: int) -> None:
        if type(year) is not int or not 1 <= year <= 9998:
            raise ValidationError("Year must be between 1 and 9998.")
