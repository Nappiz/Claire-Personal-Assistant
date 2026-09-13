class ApplicationError(Exception):
    """Compatibility error carrying the existing public status and detail."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
