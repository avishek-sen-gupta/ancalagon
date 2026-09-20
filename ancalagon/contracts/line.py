# The two things a run says about itself, discriminated on kind.
from ancalagon.contracts.lifecycle_line import LifecycleLine
from ancalagon.contracts.message_line import MessageLine

Line = LifecycleLine | MessageLine
