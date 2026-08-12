# What one run varies from every other: where it lives, where its goal is, what shape it answers in.
import typing

import pydantic


class RunSettings(pydantic.BaseModel, frozen=True):
    run_dir: str = ""
    goal_file: str = ""
    contract_module: str = ""
    contract_class: str = ""

    @pydantic.model_validator(mode="after")
    def _module_and_class_arrive_together(self) -> typing.Self:
        if bool(self.contract_module) == bool(self.contract_class):
            return self
        raise ValueError("contract_module and contract_class are both set or both empty")
