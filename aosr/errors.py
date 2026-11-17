class AosrError(Exception):
    """Ошибка с кодом для ответа команды: {"ok": false, "error": {"code", "message"}}."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
