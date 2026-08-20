# Every state an attempt can be in; the fold in attempt_of.py produces one of these.
from ancalagon.attempt.claimed import Claimed
from ancalagon.attempt.closed import Closed
from ancalagon.attempt.collected import Collected
from ancalagon.attempt.lost import Lost
from ancalagon.attempt.nascent import Nascent
from ancalagon.attempt.queued import Queued
from ancalagon.attempt.running import Running

Attempt = Nascent | Queued | Claimed | Running | Closed | Lost | Collected
