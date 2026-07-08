class OKXAPIException(Exception):
    def __init__(self, code: str, msg: str, endpoint: str = ""):
        self.code = code
        self.msg = msg
        self.endpoint = endpoint
        super().__init__(f"[{code}] {msg}" + (f" (endpoint: {endpoint})" if endpoint else ""))
