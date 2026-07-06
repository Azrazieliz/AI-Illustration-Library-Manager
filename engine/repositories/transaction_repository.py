from __future__ import annotations

from engine.database.models.transaction import Transaction
from engine.repositories.base_repository import BaseRepository


class TransactionRepository(BaseRepository[Transaction]):
    """Repository for transaction persistence operations."""

    def __init__(self) -> None:
        super().__init__(Transaction)

    def create_transaction(self, *, operation: str, old_path: str | None = None, new_path: str | None = None) -> Transaction:
        transaction = Transaction(
            operation=operation,
            status="pending",
            old_path=old_path,
            new_path=new_path,
        )
        self.add(transaction)
        self.commit()
        return transaction

    def finish_transaction(self, transaction: Transaction) -> Transaction:
        transaction.status = "completed"
        transaction.completed = True
        self.commit()
        return transaction

    def rollback_transaction(self, transaction: Transaction) -> Transaction:
        transaction.status = "rolled_back"
        transaction.rolled_back = True
        self.commit()
        return transaction

    def get_transaction(self, identifier: int) -> Transaction | None:
        return self.get_by_id(identifier)
