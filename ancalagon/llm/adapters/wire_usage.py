# The token counters a provider reports; one it does not report reads as zero.
import pydantic


class WireUsage(pydantic.BaseModel, frozen=True):
    model_config = pydantic.ConfigDict(from_attributes=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
