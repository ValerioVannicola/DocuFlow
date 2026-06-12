class DocuflowError(Exception):
    pass


class UnsupportedFileTypeError(DocuflowError):
    pass


class ParsingError(DocuflowError):
    pass


class OCRError(DocuflowError):
    pass


OCRFailure = OCRError


class SchemaExtractionError(DocuflowError):
    pass


class ValidationError(DocuflowError):
    def __init__(self, message: str, field_name: str | None = None, rule_name: str | None = None):
        self.field_name = field_name
        self.rule_name = rule_name
        super().__init__(message)


class EvidenceNotFoundError(DocuflowError):
    pass


class StorageError(DocuflowError):
    pass


class WorkflowError(DocuflowError):
    def __init__(self, message: str, result: object | None = None):
        self.result = result
        super().__init__(message)


class HumanReviewRequiredError(DocuflowError):
    def __init__(self, message: str, document_id: str | None = None, reason: str | None = None):
        self.document_id = document_id
        self.reason = reason
        super().__init__(message)


HumanReviewRequired = HumanReviewRequiredError


class PrivacyError(DocuflowError):
    pass


class AnonymizationError(PrivacyError):
    pass
