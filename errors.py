class StaticException(Exception):
    """A base genshin exception"""
    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __repr__(self) -> str:
        return f"{type(self).__name__}: {self.msg}"


class ErrorDuringImport(StaticException):
    pass
