# What one model call consumed. Tokens are facts; cost is a function of them and a
# price list that changes, so only the tokens are recorded.
import pydantic


class CallUsage(pydantic.BaseModel, frozen=True):
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
