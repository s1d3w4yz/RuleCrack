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
- **Hashcat / John the Ripper compatibility**: a target switch with three
  genuinely different views, since John's hashcat-compat rule engine is a
  strict subset of hashcat's (verified against John's own source):
  - **Hashcat** — the full operator set; every list (add-step menu, cheat
    sheet) stays complete, but the 13 operators John can't run at all
    (`3`, `B`, `h`, `H`, the nine `~`-class ops) carry a `⚠` marker and a
    badge inline, everywhere, all the time — no tab-switching needed to
    see what won't port.
  - **Both (portable)** — those 13 are dropped from the add-step menu and
    cheat sheet entirely, since they're simply not buildable for John;
    what's left behaves identically in both tools.
  - **John the Ripper** — the same portable subset, plus a distinctly
    styled (teal-bordered) reference box listing commands John has that
    hashcat (and so this tool) doesn't: pluralization, whole-string
    insert, numeric variables, … each tagged with its own `✓ John-only`
    badge — the mirror image of `⚠ HC-only`, including the `v` token
    collision where the two tools disagree on what it means even in
    John's hashcat-compat mode.
  Any chain step already added also keeps its own `⚠ HC-only` badge and
  full type dropdown regardless of target, and the Export panel always
  shows a one-line portability verdict. See the comments above
  `JOHN_UNSUPPORTED` in `index.html` for how the compatibility list was
  verified against John's own source and docs.

Operator semantics were verified against hashcat's own reference
implementation and test suite (`docs/rules.txt`, `src/rp_cpu.c`, and
`tools/rules-test-cases.yaml` in the [hashcat](https://github.com/hashcat/hashcat)
repository) — positions are 0-indexed, most positional ops silently no-op
when a position is out of range, and a handful of ops (memory extraction,
some reject filters) reject the whole candidate instead.

## Usage

Open `index.html` directly in a browser, or serve the directory statically:

```sh
python3 -m http.server 8000
```

Then visit `http://localhost:8000/`.

No build step, no dependencies — it's a single self-contained HTML file.
