"""AI Engineer credit wallet with token-based metering."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.models.platform import AiCreditAccount, AiOperation, PlatformAuditLog

# Platform credit ↔ model tokens. Tuned so short editor asks stay ~1 credit,
# not wiping a whole plan after two tool-using turns.
TOKENS_PER_CREDIT = 12_000
# Completion still costs more than prompt, but not 2× (that over-penalized tool loops).
COMPLETION_WEIGHT = 1.25
# Cap so one chat never drains a small wallet.
MAX_CREDITS_PER_CHAT = 2
CHAT_RESERVE_CREDITS = 1


def credits_from_usage(prompt_tokens: int, completion_tokens: int) -> int:
    """Convert API token usage into whole platform credits (minimum 1 when any work ran)."""
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    # Soften large prompt overhead (system + tool dumps): first 2.5k full, rest at 30%.
    if prompt > 2500:
        billable_prompt = 2500 + int((prompt - 2500) * 0.30)
    else:
        billable_prompt = prompt
    weighted = int(billable_prompt + completion * COMPLETION_WEIGHT)
    if weighted <= 0:
        return CHAT_RESERVE_CREDITS
    raw = max(1, (weighted + TOKENS_PER_CREDIT - 1) // TOKENS_PER_CREDIT)
    return min(raw, MAX_CREDITS_PER_CHAT)


def tokens_from_credits(credits: int) -> int:
    return max(0, int(credits or 0)) * TOKENS_PER_CREDIT


class AiCreditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_account(self, customer_id: UUID) -> AiCreditAccount:
        result = await self._session.execute(
            select(AiCreditAccount).where(AiCreditAccount.customer_id == customer_id)
        )
        account = result.scalar_one_or_none()
        if account is None:
            account = AiCreditAccount(customer_id=customer_id)
            self._session.add(account)
            await self._session.flush()
        return account

    async def assert_credits(self, customer_id: UUID, cost: int = 1) -> AiCreditAccount:
        account = await self.get_account(customer_id)
        if account.credits_remaining < cost:
            raise AppException("Insufficient AI Engineer credits. Top up or upgrade your plan.")
        return account

    async def start_operation(
        self,
        *,
        customer_id: UUID,
        environment_id: UUID | None,
        operation_type: str,
        permission_level: int,
        request: str,
        risk: str = "low",
        require_confirm: bool = False,
        cost: int = 1,
    ) -> AiOperation:
        if permission_level < 1 or permission_level > 4:
            raise AppException("permission_level must be 1–4.")
        account = await self.assert_credits(customer_id, cost)
        op = AiOperation(
            customer_id=customer_id,
            environment_id=environment_id,
            operation_type=operation_type,
            permission_level=permission_level,
            credits_used=cost,
            status="authorized" if not require_confirm else "pending",
            request=request,
            risk_classification=risk,
            required_confirmation=require_confirm or permission_level >= 3,
        )
        self._session.add(op)
        # Reserve credits only when auto-authorized (levels 1–2)
        if not op.required_confirmation:
            account.credits_remaining -= cost
            account.lifetime_used += cost
            op.status = "running"
        await self._session.flush()
        return op

    async def settle_chat_usage(
        self,
        customer_id: UUID,
        operation_id: UUID,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        success: bool,
        result: str,
    ) -> tuple[AiOperation, AiCreditAccount, dict[str, int]]:
        """Adjust the reserved chat charge to real token usage and return metering stats."""
        op = await self._get_op(customer_id, operation_id)
        account = await self.get_account(customer_id)
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        if prompt > 2500:
            billable_prompt = 2500 + int((prompt - 2500) * 0.30)
        else:
            billable_prompt = prompt
        weighted = int(billable_prompt + completion * COMPLETION_WEIGHT)

        if not success:
            refund = int(op.credits_used or 0)
            if refund:
                account.credits_remaining += refund
                account.lifetime_used = max(0, account.lifetime_used - refund)
            op.credits_used = 0
            op.status = "failed"
            op.result = result
            op.completed_at = datetime.now(UTC)
            await self._session.flush()
            stats = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "weighted_tokens": weighted,
                "credits_charged": 0,
                "credits_remaining": account.credits_remaining,
                "tokens_remaining": tokens_from_credits(account.credits_remaining),
                "tokens_per_credit": TOKENS_PER_CREDIT,
            }
            return op, account, stats

        actual = credits_from_usage(prompt, completion)
        reserved = int(op.credits_used or 0)
        delta = actual - reserved
        if delta > 0:
            extra = min(delta, account.credits_remaining)
            account.credits_remaining -= extra
            account.lifetime_used += extra
            actual = reserved + extra
        elif delta < 0:
            account.credits_remaining -= delta  # add back unused reserve
            account.lifetime_used = max(0, account.lifetime_used + delta)
        op.credits_used = actual
        op.status = "success"
        op.result = result
        op.completed_at = datetime.now(UTC)
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                action="ai.operation",
                target_type="ai_operation",
                target_id=str(op.id),
                result="success",
                metadata_json={
                    "type": op.operation_type,
                    "level": op.permission_level,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "credits_charged": actual,
                },
            )
        )
        await self._session.flush()
        stats = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "weighted_tokens": weighted,
            "credits_charged": actual,
            "credits_remaining": account.credits_remaining,
            "tokens_remaining": tokens_from_credits(account.credits_remaining),
            "tokens_per_credit": TOKENS_PER_CREDIT,
        }
        return op, account, stats

    async def confirm_operation(self, customer_id: UUID, operation_id: UUID) -> AiOperation:
        op = await self._get_op(customer_id, operation_id)
        if op.status not in {"pending", "authorized"}:
            raise AppException(f"Operation cannot be confirmed (status={op.status}).")
        account = await self.assert_credits(customer_id, op.credits_used)
        account.credits_remaining -= op.credits_used
        account.lifetime_used += op.credits_used
        op.status = "running"
        await self._session.flush()
        return op

    async def complete_operation(
        self, customer_id: UUID, operation_id: UUID, *, success: bool, result: str
    ) -> AiOperation:
        op = await self._get_op(customer_id, operation_id)
        op.status = "success" if success else "failed"
        op.result = result
        op.completed_at = datetime.now(UTC)
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                action="ai.operation",
                target_type="ai_operation",
                target_id=str(op.id),
                result="success" if success else "failed",
                metadata_json={"type": op.operation_type, "level": op.permission_level},
            )
        )
        await self._session.flush()
        return op

    async def grant_credits(
        self,
        customer_id: UUID,
        credits: int,
        *,
        actor_user_id: UUID | None = None,
        note: str | None = None,
    ) -> AiCreditAccount:
        """Staff/manual top-up — adds credits without a payment order."""
        amount = int(credits or 0)
        if amount < 1:
            raise ValidationError("Grant at least 1 AI credit.")
        if amount > 100_000:
            raise ValidationError("Maximum 100,000 credits per grant.")
        account = await self.get_account(customer_id)
        before = int(account.credits_remaining or 0)
        account.credits_remaining = before + amount
        account.total_allocated = int(account.total_allocated or 0) + amount
        self._session.add(
            PlatformAuditLog(
                customer_id=customer_id,
                actor_id=actor_user_id,
                action="ai.credits_granted",
                target_type="ai_credit_account",
                target_id=str(account.id),
                result="success",
                metadata_json={
                    "credits_granted": amount,
                    "credits_before": before,
                    "credits_after": account.credits_remaining,
                    "note": (note or "").strip()[:400] or None,
                },
            )
        )
        await self._session.flush()
        return account

    async def list_operations(self, customer_id: UUID, limit: int = 50) -> list[AiOperation]:
        result = await self._session.execute(
            select(AiOperation)
            .where(AiOperation.customer_id == customer_id)
            .order_by(AiOperation.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _get_op(self, customer_id: UUID, operation_id: UUID) -> AiOperation:
        result = await self._session.execute(
            select(AiOperation).where(
                AiOperation.id == operation_id, AiOperation.customer_id == customer_id
            )
        )
        op = result.scalar_one_or_none()
        if op is None:
            raise NotFoundError("AI operation not found.")
        return op
