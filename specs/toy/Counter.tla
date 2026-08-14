---- MODULE Counter ----
EXTENDS Naturals

VARIABLES x
vars == <<x>>
Init == x = 1
Next == x' = x + 1 /\ x' < 3

TypeOK == x \in Nat
Spec == Init /\ [][Next]_vars
====
