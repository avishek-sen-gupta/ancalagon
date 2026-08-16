# What one run varies from every other: where it lives, what it is asked, and as which role.
import pydantic


class RunSettings(pydantic.BaseModel, frozen=True):
    run_dir: str = ""
    goal_file: str = ""
    input_file: str = ""
    role: str = ""
