# What one run varies from every other: where it lives, where its goal is, what shape it answers in.
import pydantic


class RunSettings(pydantic.BaseModel, frozen=True):
    run_dir: str = ""
    goal_file: str = ""
    contract_module: str = ""
    contract_class: str = ""
