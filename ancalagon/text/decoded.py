# The one rule for turning bytes from outside into text: UTF-8, then Latin-1, which cannot fail.
def decoded(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")
