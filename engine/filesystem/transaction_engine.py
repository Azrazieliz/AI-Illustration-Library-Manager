from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.config import settings
from engine.database import get_database_manager
from engine.database.models.transaction import Transaction
from engine.filesystem.exceptions import ConflictError, PreviewError, RollbackError, TransactionError
from engine.filesystem.file_operations import FileOperations
from engine.filesystem.journal import TransactionJournal
from engine.filesystem.preview import PreviewTransaction
from engine.filesystem.rollback import RollbackManager, RollbackPlan


class TransactionEngine:
    """Safely execute reversible filesystem operations."""

    def __init__(self) -> None:
        self._journal = TransactionJournal(settings.log_directory)
        self._rollback_manager = RollbackManager()
        self._last_transaction: Transaction | None = None

    def preview_move(self, source: Path | str, destination: Path | str) -> PreviewTransaction:
        """Preview a move operation without executing it."""
        source_path = Path(source)
        destination_path = Path(destination)
        if not source_path.exists():
            raise PreviewError(f"Source does not exist: {source_path}")
        if destination_path.exists():
            conflicts = [f"Destination exists: {destination_path}"]
            return PreviewTransaction(
                source=source_path,
                destination=destination_path,
                operation="move",
                conflicts=conflicts,
                warnings=[],
                estimated_result="blocked",
            )
        return PreviewTransaction(
            source=source_path,
            destination=destination_path,
            operation="move",
            conflicts=[],
            warnings=[],
            estimated_result="moved",
        )

    def move(self, source: Path | str, destination: Path | str) -> bool:
        """Move a file while recording and journalizing the action."""
        source_path = Path(source)
        destination_path = Path(destination)
        preview = self.preview_move(source_path, destination_path)
        if preview.conflicts:
            raise ConflictError(preview.conflicts[0])
        return self._execute_transaction("move", source_path, destination_path)

    def rename(self, source: Path | str, destination: Path | str) -> bool:
        """Rename a file after recording the transaction."""
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path.exists():
            raise ConflictError(f"Destination already exists: {destination_path}")
        return self._execute_transaction("rename", source_path, destination_path)

    def copy(self, source: Path | str, destination: Path | str) -> bool:
        """Copy a file after recording the transaction."""
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path.exists():
            raise ConflictError(f"Destination already exists: {destination_path}")
        return self._execute_transaction("copy", source_path, destination_path)

    def restore(self, source: Path | str, destination: Path | str) -> bool:
        """Restore a file from source to destination."""
        source_path = Path(source)
        destination_path = Path(destination)
        return self._execute_transaction("restore", source_path, destination_path)

    def undo(self) -> bool:
        """Undo the most recently completed transaction."""
        if self._last_transaction is None:
            raise RollbackError("No transaction available to undo")
        plan = self._rollback_manager.pop()
        if plan.operation in {"move", "rename", "restore"}:
            if plan.destination.exists():
                if plan.source.exists():
                    raise RollbackError("Cannot undo because source already exists")
                shutil.move(str(plan.destination), str(plan.source))
            else:
                raise RollbackError("Destination no longer exists")
        elif plan.operation == "copy":
            if plan.destination.exists():
                plan.destination.unlink()
            else:
                raise RollbackError("Copied destination no longer exists")
        return True

    def rollback(self) -> bool:
        """Rollback the most recent transaction if possible."""
        try:
            return self.undo()
        except RollbackError as exc:
            raise RollbackError(f"Rollback failed: {exc}") from exc

    def _execute_transaction(self, operation_type: str, source: Path, destination: Path) -> bool:
        manager = get_database_manager()
        session = manager.session_factory()
        try:
            transaction = Transaction(
                uuid=str(uuid.uuid4()),
                operation=operation_type,
                status="pending",
                old_path=str(source),
                new_path=str(destination),
                rollback_data=json.dumps({"source": str(source), "destination": str(destination)}),
            )
            session.add(transaction)
            session.commit()
            self._journal.write(
                {
                    "id": transaction.id,
                    "operation_type": operation_type,
                    "source_path": str(source),
                    "destination_path": str(destination),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "completed": False,
                    "rolled_back": False,
                    "error_message": None,
                }
            )

            if operation_type == "move":
                FileOperations.move(source, destination)
            elif operation_type == "rename":
                FileOperations.rename(source, destination)
            elif operation_type == "copy":
                FileOperations.copy(source, destination)
            elif operation_type == "restore":
                FileOperations.restore(source, destination)
            else:
                raise TransactionError(f"Unsupported operation: {operation_type}")

            transaction.status = "completed"
            transaction.completed = True
            session.commit()
            self._last_transaction = transaction
            self._rollback_manager.add(RollbackPlan(source, destination, operation_type, completed=True))
            return True
        except Exception as exc:
            transaction.status = "failed"
            transaction.error_message = str(exc)
            session.commit()
            raise
        finally:
            session.close()
