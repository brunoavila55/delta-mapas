from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .exceptions import (
    CreditInvariantError,
    CreditOperationConflict,
    InsufficientCredits,
    ProcessingPriceNotConfigured,
)
from .models import CreditAccount, CreditTransaction, ProcessingPrice


@dataclass(frozen=True)
class CreditOperationResult:
    account: CreditAccount
    ledger_entry: CreditTransaction
    replayed: bool


def get_processing_cost(index_type: str) -> int:
    try:
        price = ProcessingPrice.objects.get(index_type=index_type, is_active=True)
    except ProcessingPrice.DoesNotExist as exc:
        raise ProcessingPriceNotConfigured(
            f"Não há preço ativo configurado para {index_type}."
        ) from exc
    return price.credit_cost


def _locked_account() -> CreditAccount:
    account, _ = CreditAccount.objects.get_or_create(singleton_key=True)
    return CreditAccount.objects.select_for_update().get(pk=account.pk)


def lock_credit_account() -> CreditAccount:
    """Lock the tenant's singleton account inside the caller's atomic transaction."""
    return _locked_account()


def _validate_replay(
    entry: CreditTransaction,
    *,
    transaction_type: str,
    amount: int,
    map_job,
) -> None:
    expected_job_id = getattr(map_job, "id", None)
    if (
        entry.transaction_type != transaction_type
        or entry.amount != amount
        or entry.map_job_id != expected_job_id
    ):
        raise CreditOperationConflict(
            "A chave idempotente já foi utilizada com parâmetros diferentes."
        )


def _existing_operation(
    *,
    idempotency_key: str,
    transaction_type: str,
    amount: int,
    map_job,
) -> CreditOperationResult | None:
    entry = (
        CreditTransaction.objects.select_related("account")
        .filter(idempotency_key=idempotency_key)
        .first()
    )
    if entry is None:
        return None
    _validate_replay(
        entry,
        transaction_type=transaction_type,
        amount=amount,
        map_job=map_job,
    )
    return CreditOperationResult(entry.account, entry, replayed=True)


@transaction.atomic
def grant_credits(
    *,
    amount: int,
    idempotency_key: str,
    transaction_type: str = CreditTransaction.Type.BONUS,
    created_by=None,
    metadata: dict | None = None,
) -> CreditOperationResult:
    if amount <= 0:
        raise ValueError("Credit amount must be positive.")
    if transaction_type not in {
        CreditTransaction.Type.PURCHASE,
        CreditTransaction.Type.BONUS,
        CreditTransaction.Type.REFUND,
        CreditTransaction.Type.ADMIN_ADJUSTMENT,
    }:
        raise CreditOperationConflict("Tipo inválido para adição de créditos.")

    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=transaction_type,
        amount=amount,
        map_job=None,
    )
    if existing:
        return existing

    account = _locked_account()
    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=transaction_type,
        amount=amount,
        map_job=None,
    )
    if existing:
        return existing
    account.available_balance += amount
    account.save(update_fields=("available_balance", "updated_at"))
    entry = CreditTransaction.objects.create(
        account=account,
        transaction_type=transaction_type,
        amount=amount,
        idempotency_key=idempotency_key,
        available_balance_after=account.available_balance,
        reserved_balance_after=account.reserved_balance,
        created_by=created_by,
        metadata=metadata or {},
    )
    return CreditOperationResult(account, entry, replayed=False)


@transaction.atomic
def adjust_available_credits(
    *,
    delta: int,
    idempotency_key: str,
    reason: str,
    created_by=None,
) -> CreditOperationResult:
    if delta == 0:
        raise ValueError("Credit adjustment cannot be zero.")
    amount = abs(delta)

    def existing_adjustment() -> CreditOperationResult | None:
        entry = (
            CreditTransaction.objects.select_related("account")
            .filter(idempotency_key=idempotency_key)
            .first()
        )
        if entry is None:
            return None
        if (
            entry.transaction_type != CreditTransaction.Type.ADMIN_ADJUSTMENT
            or entry.amount != amount
            or entry.metadata.get("delta") != delta
        ):
            raise CreditOperationConflict(
                "A chave idempotente já foi utilizada com outro ajuste."
            )
        return CreditOperationResult(entry.account, entry, replayed=True)

    existing = existing_adjustment()
    if existing:
        return existing
    account = _locked_account()
    existing = existing_adjustment()
    if existing:
        return existing
    if delta < 0 and account.available_balance < amount:
        raise InsufficientCredits("Saldo insuficiente para o ajuste solicitado.")

    account.available_balance += delta
    account.save(update_fields=("available_balance", "updated_at"))
    entry = CreditTransaction.objects.create(
        account=account,
        transaction_type=CreditTransaction.Type.ADMIN_ADJUSTMENT,
        amount=amount,
        idempotency_key=idempotency_key,
        available_balance_after=account.available_balance,
        reserved_balance_after=account.reserved_balance,
        created_by=created_by,
        metadata={"delta": delta, "reason": reason},
    )
    return CreditOperationResult(account, entry, replayed=False)


@transaction.atomic
def reserve_credits(
    *,
    map_job,
    amount: int,
    idempotency_key: str,
    created_by=None,
) -> CreditOperationResult:
    if amount <= 0:
        raise ValueError("Credit amount must be positive.")
    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=CreditTransaction.Type.RESERVE,
        amount=amount,
        map_job=map_job,
    )
    if existing:
        return existing

    account = _locked_account()
    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=CreditTransaction.Type.RESERVE,
        amount=amount,
        map_job=map_job,
    )
    if existing:
        return existing
    if account.available_balance < amount:
        raise InsufficientCredits("Saldo de créditos insuficiente.")
    account.available_balance -= amount
    account.reserved_balance += amount
    account.save(update_fields=("available_balance", "reserved_balance", "updated_at"))
    entry = CreditTransaction.objects.create(
        account=account,
        transaction_type=CreditTransaction.Type.RESERVE,
        amount=amount,
        idempotency_key=idempotency_key,
        map_job=map_job,
        available_balance_after=account.available_balance,
        reserved_balance_after=account.reserved_balance,
        created_by=created_by,
    )
    return CreditOperationResult(account, entry, replayed=False)


def _reservation_for_job(map_job) -> CreditTransaction:
    try:
        return CreditTransaction.objects.get(
            map_job=map_job,
            transaction_type=CreditTransaction.Type.RESERVE,
        )
    except CreditTransaction.DoesNotExist as exc:
        raise CreditInvariantError("O job não possui uma reserva de créditos.") from exc


@transaction.atomic
def capture_reserved_credits(*, map_job, created_by=None) -> CreditOperationResult:
    reservation = _reservation_for_job(map_job)
    amount = reservation.amount
    idempotency_key = f"map-job:{map_job.id}:capture"
    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=CreditTransaction.Type.CAPTURE,
        amount=amount,
        map_job=map_job,
    )
    if existing:
        return existing
    if CreditTransaction.objects.filter(
        map_job=map_job, transaction_type=CreditTransaction.Type.RELEASE
    ).exists():
        raise CreditOperationConflict("Créditos já liberados não podem ser capturados.")

    account = CreditAccount.objects.select_for_update().get(pk=reservation.account_id)
    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=CreditTransaction.Type.CAPTURE,
        amount=amount,
        map_job=map_job,
    )
    if existing:
        return existing
    if CreditTransaction.objects.filter(
        map_job=map_job, transaction_type=CreditTransaction.Type.RELEASE
    ).exists():
        raise CreditOperationConflict("Créditos já liberados não podem ser capturados.")
    if account.reserved_balance < amount:
        raise CreditInvariantError("Saldo reservado inconsistente.")
    account.reserved_balance -= amount
    account.save(update_fields=("reserved_balance", "updated_at"))
    entry = CreditTransaction.objects.create(
        account=account,
        transaction_type=CreditTransaction.Type.CAPTURE,
        amount=amount,
        idempotency_key=idempotency_key,
        map_job=map_job,
        available_balance_after=account.available_balance,
        reserved_balance_after=account.reserved_balance,
        created_by=created_by,
    )
    return CreditOperationResult(account, entry, replayed=False)


@transaction.atomic
def release_reserved_credits(*, map_job, created_by=None) -> CreditOperationResult:
    reservation = _reservation_for_job(map_job)
    amount = reservation.amount
    idempotency_key = f"map-job:{map_job.id}:release"
    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=CreditTransaction.Type.RELEASE,
        amount=amount,
        map_job=map_job,
    )
    if existing:
        return existing
    if CreditTransaction.objects.filter(
        map_job=map_job, transaction_type=CreditTransaction.Type.CAPTURE
    ).exists():
        raise CreditOperationConflict("Créditos capturados não podem ser liberados.")

    account = CreditAccount.objects.select_for_update().get(pk=reservation.account_id)
    existing = _existing_operation(
        idempotency_key=idempotency_key,
        transaction_type=CreditTransaction.Type.RELEASE,
        amount=amount,
        map_job=map_job,
    )
    if existing:
        return existing
    if CreditTransaction.objects.filter(
        map_job=map_job, transaction_type=CreditTransaction.Type.CAPTURE
    ).exists():
        raise CreditOperationConflict("Créditos capturados não podem ser liberados.")
    if account.reserved_balance < amount:
        raise CreditInvariantError("Saldo reservado inconsistente.")
    account.reserved_balance -= amount
    account.available_balance += amount
    account.save(update_fields=("available_balance", "reserved_balance", "updated_at"))
    entry = CreditTransaction.objects.create(
        account=account,
        transaction_type=CreditTransaction.Type.RELEASE,
        amount=amount,
        idempotency_key=idempotency_key,
        map_job=map_job,
        available_balance_after=account.available_balance,
        reserved_balance_after=account.reserved_balance,
        created_by=created_by,
    )
    return CreditOperationResult(account, entry, replayed=False)
