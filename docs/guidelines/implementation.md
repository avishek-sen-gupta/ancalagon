## Implementation Guidelines

- When a design question hinges on what a real external system does (a library's actual behaviour, a protocol spec, an API's constraints), research it first — don't guess and don't default straight to asking the user. Reserve user questions for genuine judgement calls that research can't resolve.
- When the user asks to scope to a specific subdirectory or module, scope precisely. Don't run on the broader repo.
- When working with LLM APIs, start with small test inputs before processing large datasets.
- Review subagent output for workaround guards (`is not None` checks that mask bugs).

## Interaction Style

- **Write short, plain sentences.** No throat-clearing and no inflation. Words like *sharp*, *sharper*, *load-bearing*, *precise*, *worth being precise*, *the crux*, *decisively* are padding that makes a plain statement sound like an insight. Say the thing.
- **Keep a response to ten or twelve lines**, not counting code and command output. If it will not fit, the answer is too broad — narrow it or ask.
- **One decision per turn.** When several things need deciding, present the first, wait, then the next. A list of choices in one turn puts the work of sequencing them on the user.
- When interrupted or cancelled, immediately proceed with the new instruction. No clarifying questions — treat interruptions as implicit redirects.
- **Brainstorm collaboratively.** When thinking through approaches, present options and trade-offs to the user and actively incorporate their input before proceeding. Do not pick an approach and start implementing without discussion. The user's judgment on complexity/correctness trade-offs overrides the agent's default.
- **Stop and consult when patching.** If an implementation requires more than one corrective patch (fix-on-fix), stop. The design is wrong. Re-brainstorm the approach with the user before adding more patches. Accumulating compensating transforms is a sign the underlying model doesn't match reality.

## Python Introspection

- Write temporary scripts to the scratchpad directory and execute with `uv run python <path>`.
- Clean up temp files after use.
- Do not use `python -c` with multiline strings.
