# Arguments for fetching one page.
import pydantic


class FetchArgs(pydantic.BaseModel, frozen=True):
    url: str = pydantic.Field(
        pattern=r"^https://", description="An https URL. Plain http is refused."
    )
