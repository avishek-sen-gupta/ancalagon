# Names one contract class a parent wrote, by the workspace path it wrote it to.
import pydantic


class ContractSource(pydantic.BaseModel, frozen=True):
    path: str = ""
    name: str = pydantic.Field(default="FreeText", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
