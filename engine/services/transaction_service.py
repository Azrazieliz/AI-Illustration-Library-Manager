from __future__ import annotations

from engine.database.models.transaction import Transaction
from engine.repositories.transaction_repository import TransactionRepository
from engine.services.base_service import BaseService


class TransactionService(BaseService[Transaction]):
    """Service layer for transaction records."""

    def __init__(self, repository: TransactionRepository | None = None) -> None:
        super().__init__(repository or TransactionRepository())
        self.repository = repository or TransactionRepository()

    def create_transaction(self, *, operation: str, old_path: str | None = None, new_path: str | None = None) -> Transaction:
        return self.repository.create_transaction(operation=operation, old_path=old_path, new_path=new_path)

    def finish_transaction(self, transaction: Transaction) -> Transaction:
        return self.repository.finish_transaction(transaction)

    def rollback_transaction(self, transaction: Transaction) -> Transaction:
        return self.repository.rollback_transaction(transaction)

    def get_transaction(self, identifier: int) -> Transaction | None:
        return self.repository.get_transaction(identifier)
