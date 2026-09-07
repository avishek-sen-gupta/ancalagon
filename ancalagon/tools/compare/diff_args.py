# The two ranges diff_regions compares.
import pydantic

from ancalagon.tools.compare.region import Region


class DiffArgs(pydantic.BaseModel, frozen=True):
    left: Region
    right: Region
