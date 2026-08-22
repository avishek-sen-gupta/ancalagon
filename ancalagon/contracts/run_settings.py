# What one run varies from every other: what it is asked, and as which role.
import pydantic


class RunSettings(pydantic.BaseModel, frozen=True):
    goal_file: str = ""
    input_file: str = ""
    role: str = ""
