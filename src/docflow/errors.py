class DocflowError(Exception):
    pass


class UnsupportedFileTypeError(DocflowError):
    pass


class ParsingError(DocflowError):
    pass


class OCRError(DocflowError):
    pass


OCRFailure = OCRError


class SchemaExtractionError(DocflowError):
    pass


class ValidationError(DocflowError):
    def __init__(self, message: str, field_name: str | None = None, rule_name: str | None = None):
        self.field_name = field_name
        self.rule_name = rule_name
        super().__init__(message)


class EvidenceNotFoundError(DocflowError):
    pass


class StorageError(DocflowError):
    pass


class WorkflowError(DocflowError):
    def __init__(self, message: str, result: object | None = None):
        self.result = result
        super().__init__(message)


class HumanReviewRequiredError(DocflowError):
    def __init__(self, message: str, document_id: str | None = None, reason: str | None = None):
        self.document_id = document_id
        self.reason = reason
        super().__init__(message)


HumanReviewRequired = HumanReviewRequiredError


class PrivacyError(DocflowError):
    pass


class AnonymizationError(PrivacyError):
    pass
