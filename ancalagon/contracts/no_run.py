# The run function a role served by a model names: there is not one.
from ancalagon.contracts.function_ref import FunctionRef


def no_run() -> None:
    raise NotImplementedError("this role is served by a model, not by a run function")


NO_RUN = FunctionRef(module="ancalagon.contracts.no_run", name="no_run")
