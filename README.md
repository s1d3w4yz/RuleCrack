# Rule Chain Lab

A single-page tool for learning how password-cracking rules work: build an
ordered chain of transformation steps, watch each step apply one at a time,
and see how reordering the chain changes the result. Covers both hashcat's
and John the Ripper's rule syntax — hashcat is the recommended default
(unambiguous, what most public rule lists use, and John runs it identically
in its own hashcat-compat mode), with John's native syntax available for the
handful of things hashcat genuinely can't express. Export the chain as a
real `.rule` line, batch-test it against a list of words, or switch to the
separate rulefile validator view to check, fix, and clean up an entire
existing `.rule` file line by line.

## What it does

- **Full operator coverage**: every mangle, byte-math, encoding, memory, and
  reject operator from hashcat's rule engine — capitalize/toggle/shift case,
  reverse/rotate/duplicate, insert/delete/extract/omit/overstrike, char
  substitution and purging, bitwise/byte-arithmetic ops, hex encoding,
  memory ops (`M 4 6 X Q`), length/content reject filters, and the
  class-based (`~`) variants. Grouped by category in the add-step menu.
- **Step chain**: steps run top to bottom. Reorder them by dragging or with
  the arrow buttons and watch the output change — this is the core lesson: rule order
  changes the result.
- **Rule line**: the rule as plain text. Paste or type one (your own, or a
  line from an existing `.rule` file) and it's parsed straight into the
  step chain below, using the same engine as the visual builder — no
  separate "mode" or view, just another way to drive the same chain. It
  works both ways: changes you make to the chain (adding, reordering,
  editing, deleting) rewrite the line, and a disabled step keeps its token
  in the line, struck through.
- **Step-by-step trace**: see the word after each individual step, with the
  part that changed highlighted. Reject steps stop the chain and mark the
  candidate as discarded, matching real hashcat behavior.
- **Copying**: the rule line (section 02) is a standard Hashcat rule line
  (e.g. `c sa4 se3 si1 so0 ss5 $! $1`) — its button copies it, ready to drop
  into a `.rule` file, and a note under it says whether it also runs in John
  the Ripper. Section 04 has a button for the final word.
- **Batch test**: run the whole chain against a list of words (one per line)
  to see how it generalizes beyond a single example.
- **Cheat sheet**: every operator listed with its abstract syntax
  (`sXY`, `TN`, `~s?CY`, …) and a concrete, clickable example built from the
  same engine that runs the chain — click one to drop it straight into the
  rule line, for learning the syntax by typing instead of clicking through
  the chain builder. A search box filters by operator or description
  (with an "Operators only" option).
- **Display options**: a Dark / Light theme and three text sizes (every size in
  the page scales together). Both are remembered per browser. The default
  size is compact enough for the three columns to fit one screen; the
  larger sizes are there when you need more readable text.
  The three columns are sized to end together within the window and
  re-fit when you resize it (devtools opening, maximizing, zooming); below
  1150px wide they stack and the lists use fixed heights instead.
- **Accessibility**: a real HTML document (language, viewport, one `<main>`),
  skip links, an accessible name on every control (each step's checkbox,
  arguments and buttons say which step they belong to), toggle buttons that
  report their pressed state, a visible focus ring, and spoken updates for
  moves, deletes, copies, the chain's result and search results. The tests
  check these so they don't regress.
- **Hashcat / John the Ripper compatibility**: a three-way target switch,
  since John's rule engine and hashcat's overlap but neither is a subset of
  the other — hashcat has 13 operators John never implements at all, and
  John has its own native grammar with commands hashcat has no concept of
  (verified against both projects' own source, not from memory):
  - **Hashcat** — the full 70-operator set. The 13 hashcat-only ops (`3`,
    `B`, `h`, `H`, the nine `~`-class ops) carry a `[Hashcat only]` tag
    inline, everywhere, all the time — no tab-switching needed to see
    what won't port to John.
  - **Both (hashcat-compatible)** — those 13 are dropped entirely; what's
    left (57 ops) behaves identically in hashcat and in John's
    hashcat-compat mode (`!! hashcat logic ON`), plus a reference box of
    John-exclusive commands this tool doesn't build in this mode. (This
    used to be two separate tabs — "Both (portable)" and "John (hashcat
    rules)" — until it became clear they built the exact same 57-op subset
    and differed only in that reference box, so they were merged into one.)
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
  Any chain step already added keeps its own compatibility badge, and its
  type dropdown is filtered by the current target the same way the "+ add
  step" menu is — except the step's own current type always stays in the
  list even if it fails that filter, so switching target never silently
  breaks or changes a step you already built. The note under the
  rule line always gives a one-line portability verdict for whichever
  direction is relevant.
  The cheat sheet itself uses color instead of a badge per row — a
  hashcat-only syntax token is always red, a John-only one always teal,
  and a shared one stays the default color — so a dense reference list of
  70+ rows stays scannable instead of growing a text pill on every line.
  A small color key pins at the top of the cheat sheet card, and the
  note under the rule line names any step that isn't portable.
- **Rulefile validator**: a separate top-level view (toggle at the very top
  of the page, next to the title) for checking an entire existing `.rule`
  file instead of building one chain — paste it in, pick which dialect it's
  written in (hashcat or John native; there's no reliable way to
  auto-detect this, since `p`/`R`/`L`/`v`/`+`/`-` are valid tokens in both
  dialects with different meanings, so you have to say which engine the
  file targets, same as a real `!! hashcat logic ON/OFF` boundary would
  require), and get a real per-line parse — not a guess — using the same
  parser the single-line input in section 02 uses. Blank lines and `#`
  comments pass through untouched. Each rule line gets a live status (valid,
  or the parser's own error with position), an output preview against the
  same sample word as section 01, an inline-editable text box for quick
  fixes (re-parses on every keystroke without losing focus), a delete/
  restore toggle, and a "Fix in builder" button that sends the line to the
  full chain builder — forcing it onto the matching dialect — for the full
  trace/cheat-sheet/batch-test treatment, with a "Save fix & return" button
  back under the builder's rule line to write the result back into the
  right row. An export panel joins every non-deleted line (comments and
  blanks included, original order preserved) into a copyable, cleaned
  rulefile.

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

## Tests

```sh
python3 tests/run_tests.py   # the rule engine in isolation
python3 tests/test_ui.py     # the same rule-handling, driven through the actual UI
```

The first checks parsing/tokenizing/running a chain against test
vectors from hashcat's own test suite and John's documentation. The
second drives the real page (adding chain steps, typing a rule line,
pasting a rulefile into the validator) and checks the result against
what the engine itself independently predicts for the same input.
Neither reimplements the engine's rules in Python — both check that
this project's own engine agrees with an external or independently-
computed source. See [`tests/README.md`](tests/README.md) for how each
one works and what they do and don't cover.

## License

[MIT](LICENSE) — update the copyright line in `LICENSE` with your own name
or handle before publishing.
