from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.api.transactions.enums import TransactionFailureReason
from backend.app.api.transactions.models import Transaction
from backend.app.api.transactions.utils import mark_transaction_failed
from backend.app.core.ai.config import ai_settings
from backend.app.core.ai.enums import AIReviewStatusEnum
from backend.app.core.ai.models import TransactionRisk
from backend.app.core.ai.transaction_analyzer import TransactionAnalyzer
from backend.app.core.logging import get_logger

logger = get_logger()


class TransactionAIService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.analyzer = TransactionAnalyzer()

    async def analyze_transaction(
        self, transaction: Transaction, user_id: UUID
    ) -> dict:
        try:
            risk_score, risk_factors = await self.analyzer.analyze_transaction(
                transaction, user_id, self.session
            )

            risk_score_record = TransactionRisk(
                transaction_id=transaction.id,
                risk_score=risk_score,
                risk_factors=risk_factors,
                ai_model_version=ai_settings.MODEL_VERSION,
            )

            self.session.add(risk_score_record)

            needs_review = risk_score >= ai_settings.RISK_SCORE_THRESHOLD

            transaction.ai_review_status = (
                AIReviewStatusEnum.FLAGGED
                if needs_review
                else AIReviewStatusEnum.CLEARED
            )

            await self.session.commit()
            await self.session.refresh(transaction)
            await self.session.refresh(risk_score_record)

            response = {
                "risk_score": risk_score,
                "risk_factors": risk_factors,
                "needs_review": needs_review,
                "recommendation": "block" if needs_review else "allow",
                "model_version": ai_settings.MODEL_VERSION,
                "score_id": risk_score_record.id,
            }

            if needs_review:
                logger.warning(f"High risk transaction detected: {transaction.id}, ")
            return response
        except Exception as e:
            logger.error(f"Error analyzing transaction: {e}")
            return {
                "risk_score": 0.8,
                "risk_factors": {"error": str(e)},
                "needs_review": True,
                "recommendation": "block",
                "model_version": "fallback",
                "error": str(e),
            }

    async def handle_flagged_transaction(
        self, transaction: Transaction, risk_analysis: dict[str, Any]
    ) -> None:
        try:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.SUSPICIOUS_ACTIVITY,
                details={
                    "risk_score": risk_analysis["risk_score"],
                    "risk_factors": risk_analysis["risk_factors"],
                    "model_version": risk_analysis.get("model_version", "unknown"),
                    "model_details": risk_analysis.get("model_details", {}),
                },
                session=self.session,
                error_message="This transaction has been flagged as potentially fraudulent. An account executive "
                "will review the transaction, before its "
                "either approved or rejected",
            )

            transaction.ai_review_status = AIReviewStatusEnum.FLAGGED

            await self.session.commit()
        except Exception as e:
            logger.error(f"Error handling flagged transaction: {e}")
            raise

    async def get_transaction_risk_history(
        self,
        user_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_risk_score: float | None = None,
    ) -> list[TransactionRisk]:
        try:
            query = (
                select(TransactionRisk)
                .join(Transaction)
                .where(Transaction.sender_id == user_id)
            )

            if start_date:
                query = query.where(Transaction.created_at >= start_date)
            if end_date:
                query = query.where(Transaction.created_at <= end_date)
            if min_risk_score:
                query = query.where(TransactionRisk.risk_score >= min_risk_score)

            result = await self.session.exec(query)

            return list(result)

        except Exception as e:
            logger.error(f"Error getting transaction risk history: {e}")
            raise

    async def mark_confirmed_fraud(
        self, transaction_id: UUID, reviewer_id: UUID, notes: str | None = None
    ) -> TransactionRisk:
        try:
            query = (
                select(TransactionRisk, Transaction)
                .join(Transaction)
                .where(Transaction.id == transaction_id)
            )
            result = await self.session.exec(query)
            transaction_risk_data = result.first()

            if not transaction_risk_data:
                raise ValueError("Transaction risk not found")

            transaction_risk, transaction = transaction_risk_data

            transaction_risk.is_confirmed_fraud = True
            transaction_risk.reviewer_id = reviewer_id
            transaction_risk.notes = notes

            if transaction:
                transaction.ai_review_status = AIReviewStatusEnum.CONFIRMED_FRAUD

                if not transaction.transaction_metadata:
                    transaction.transaction_metadata = {}

                transaction.transaction_metadata["fraud_review"] = {
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "reviewed_by": reviewer_id,
                    "notes": notes,
                }

            await self.session.commit()
            await self.session.refresh(transaction_risk)

            return transaction_risk
        except Exception as e:
            logger.error(f"Error marking confirmed fraud: {e}")
            raise
