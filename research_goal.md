Survey how the current tooling for getting **structured output out of LLMs** actually works,
and where the approaches genuinely differ.

Your training data is out of date on this subject. Treat anything you already believe as a
hypothesis to check against a page you have fetched, not as a finding. If a source and your
recollection disagree, the source wins and you say so.

Cover three areas, one per researcher:

1. **Provider-native structured output.** What the major model APIs offer directly — JSON modes,
   schema-constrained decoding, tool/function calling used as an output contract. What is
   guaranteed versus merely encouraged, and what happens when the model cannot satisfy the schema.

2. **Constrained decoding libraries.** The libraries that enforce a grammar or schema during
   sampling rather than after it. How enforcement actually works, what it costs, and which model
   access it requires (logits, or an API you cannot reach into).

3. **Validate-and-retry libraries.** The approaches that let the model generate freely and then
   parse, validate and re-ask on failure. What they do when validation fails repeatedly, and what
   they can promise that the other two cannot.

For every claim that matters, cite the URL you read it on. A claim you could not find a source
for must be marked as unverified rather than dropped or asserted.

The answer is a written report, on disk, not a reply. End it with a short section naming what you
could not determine and why.
