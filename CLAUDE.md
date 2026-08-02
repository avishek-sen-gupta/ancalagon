# RedDragon — Agent Instructions

#import .claude/core/project-context.md
#import .claude/core/workflow.md
#import .claude/core/implementation.md
#import .claude/core/tools-search.md
#import .claude/conditional/design-principles.md
#import .claude/conditional/testing-patterns.md

## Guardrails

These override defaults and are not negotiable.

**No gold plating.** Build what was asked for and nothing more. No abstraction layers, extension points, configuration knobs, or generality that no current caller needs. Simple enough that a human reading it understands it without explanation.

**No comments.** The only permitted comment is a one-line header on a class or module stating its purpose. A comment anywhere else means the code failed to explain itself — rewrite the code instead of annotating it. No docstrings on functions, no inline explanations, no section dividers, no TODOs.

**Few tests, each covering a whole behaviour.** Aggregate assertions logically into single tests. One test per coherent behaviour, asserting everything that behaviour implies — not one test per assertion. A module with eight behaviours gets eight tests, not eighty.
