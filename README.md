# Rule Chain Lab

A single-page tool for learning how hashcat-style mask rules work: build an
ordered chain of transformation steps from hashcat's full rule-based-attack
operator set, watch each step apply one at a time, and see how reordering the
chain changes the result. Export the chain as a real Hashcat `.rule` line,
and batch-test it against a list of words.

## What it does

- **Full operator coverage**: every mangle, byte-math, encoding, memory, and
  reject operator from hashcat's rule engine — capitalize/toggle/shift case,
  reverse/rotate/duplicate, insert/delete/extract/omit/overstrike, char
  substitution and purging, bitwise/byte-arithmetic ops, hex encoding,
  memory ops (`M 4 6 X Q`), length/content reject filters, and the
  class-based (`~`) variants. Grouped by category in the add-step menu.
- **Step chain**: steps run top to bottom. Reorder them with the arrow
  buttons and watch the output change — this is the core lesson: rule order
  changes the result.
- **Type a rule line**: paste or type a raw hashcat rule (your own, or a
  line from an existing `.rule` file) and it's parsed straight into the
  step chain below, using the same engine as the visual builder — no
  separate "mode" or view, just another way to drive the same chain.
- **Step-by-step trace**: see the word after each individual step, with the
  part that changed highlighted. Reject steps stop the chain and mark the
  candidate as discarded, matching real hashcat behavior.
- **Hashcat rule export**: the chain renders as a standard Hashcat rule line
  (e.g. `c sa4 se3 si1 so0 ss5 $! $1`), ready to drop into a `.rule` file.
- **Batch test**: run the whole chain against a list of words (one per line)
  to see how it generalizes beyond a single example.
- **Cheat sheet**: every operator listed with its abstract syntax
  (`sXY`, `TN`, `~s?CY`, …) and a concrete, clickable example built from the
  same engine that runs the chain — click one to drop it straight into the
  rule line, for learning the syntax by typing instead of clicking through
  the chain builder.
- **Hashcat / John the Ripper compatibility**: a four-way target switch,
  since John's rule engine and hashcat's overlap but neither is a subset of
  the other — hashcat has 13 operators John never implements at all, and
  John has its own native grammar with commands hashcat has no concept of
  (verified against both projects' own source, not from memory):
  - **Hashcat** — the full 70-operator set. The 13 hashcat-only ops (`3`,
    `B`, `h`, `H`, the nine `~`-class ops) carry a `⚠` marker and badge
    inline, everywhere, all the time — no tab-switching needed to see
    what won't port to John.
  - **Both (portable)** — those 13 are dropped entirely; what's left (57
    ops) behaves identically in hashcat and in John's hashcat-compat mode.
  - **John (hashcat rules)** — the same portable 57, framed as "hashcat
    syntax running inside John," plus a reference box of John-exclusive
    commands this tool doesn't build in this mode.
  - **John (native rules)** — switches to building rules in **John's own
    syntax** instead. The 20 commands John has that hashcat can't express
    at all — pluralization/past-tense/-ing-form, whole-string insert,
    per-position keyboard-shift, vowel/consonant swap, UTF-8 validity
    reject, early length-limit reject, the whole-word keyboard-adjacency
    shift, and John's own (non-`~`) character classes — become real,
    runnable, exportable steps here, each tagged `✓ John-only`. A separate
    John-native parser understands this syntax too (including the
    `p`/`pN` and `R`/`RN`/`L`/`LN` ambiguity John itself resolves by
    whether a digit follows), and the rule-line export switches to John
    syntax and relabels its copy button accordingly. The pluralize/past-
    tense/-ing-form heuristics and the QWERTY keyboard-adjacency tables
    are ported line-for-line from John's `rules.c`, not approximated —
    verified against the worked examples in John's own `doc/RULES`
    (`Crack96` → `cRACK(^` / `CRaCK96` / `Vtsvl07` / `Xeaxj85` for
    `S`/`V`/`R`/`L`). A handful of John features stay reference-only even
    here (numeric variables as position arguments, the target-format-
    dependent line-level reject flags, single-crack word-pair commands) —
    see the comments above `JOHN_ONLY` in `index.html` for why each one
    is out of scope.
  Any chain step already added keeps its own compatibility badge and full
  type dropdown regardless of target, and the Export panel always shows a
  one-line portability verdict for whichever direction is relevant.

Hashcat operator semantics were verified against hashcat's own reference
implementation and test suite (`docs/rules.txt`, `src/rp_cpu.c`, and
`tools/rules-test-cases.yaml` in the [hashcat](https://github.com/hashcat/hashcat)
repository) — positions are 0-indexed, most positional ops silently no-op
when a position is out of range, and a handful of ops (memory extraction,
some reject filters) reject the whole candidate instead. John-specific
semantics (including the hashcat-compat-mode disambiguation rules and the
native grammar) were verified against `doc/RULES`, `doc/RULES-hashcat`, and
`src/rules.c` in the [John the Ripper jumbo](https://github.com/openwall/john)
repository.

## Usage

Open `index.html` directly in a browser, or serve the directory statically:

```sh
python3 -m http.server 8000
```

Then visit `http://localhost:8000/`.

No build step, no dependencies — it's a single self-contained HTML file.
