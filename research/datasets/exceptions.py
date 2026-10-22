"""Custom exceptions for the REXI Research Data Lake subsystem."""


class DataLakeError(Exception):
    """Base exception for all research data lake errors."""


class DatasetNotFoundError(DataLakeError):
    """Raised when a requested dataset cannot be located in the catalog or filesystem."""


class DatasetExistsError(DataLakeError):
    """Raised when attempting to create a dataset that already exists without overwrite flag."""


class DatasetLockError(DatasetExistsError):
    """Raised when a dataset write lock cannot be acquired due to active concurrency."""


class DatasetIntegrityError(DataLakeError):
    """Raised when a dataset fails integrity checks (checksum mismatch, file missing, corrupted)."""


class SchemaMismatchError(DataLakeError):
    """Raised when a dataset or record batch schema does not conform to the registered schema."""


class IncompatibleSchemaError(SchemaMismatchError):
    """Raised when schema version is not backward compatible with registered versions."""


class InvalidDatasetNameError(DataLakeError):
    """Raised when a dataset name or ID violates naming conventions or attempts path traversal."""


class IncompleteDatasetError(DataLakeError):
    """Raised when accessing a dataset whose write was interrupted or manifest is incomplete."""
