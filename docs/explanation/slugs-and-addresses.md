# Slugs and addresses

A vocabulary's slug and a record's slug are both derived from their own published identifier — its
fragment where it has one, otherwise the last segment of its path — assigned once, on first import,
and never recomputed by a later one. A vocabulary loaded from `CONTROLLED_VOCABULARIES` takes its
declared key instead. A vocabulary's name arriving in a different language on a later
import never moves its local address. Only the publisher reassigning the identifier itself does.

That permanence has a cost worth naming: a vocabulary published under opaque codes gets an opaque
local address — `/v-113/00123` rather than `/soil-types/clay`. It is accepted because the address
is correct and stays correct, which is what every consumer of a URL needs from it, and because a
readable address that can move under data already pointing at it is worse than a stable one that
cannot.

A record another vocabulary holds moves into the vocabulary being imported only when the file places
it there with `skos:inScheme`, `skos:topConceptOf` or `skos:hasTopConcept`. It takes a new slug in
its new vocabulary, because a URI is held once.
