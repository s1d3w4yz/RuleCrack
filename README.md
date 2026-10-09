# RuleCrack

A single-page tool for learning how password-cracking rules work. Build an
ordered chain of transformation steps, watch each one apply, and see how
reordering the chain changes the result — in both **hashcat** and **John the
Ripper** syntax.

Export the chain as a real `.rule` line, batch-test it against a list of
words, or switch to the rulefile validator to check, fix, and clean up an
entire existing `.rule` file.

> Use only on systems you're authorized to test.

## Features

| | |
|---|---|
| **Full operator coverage** | Every hashcat operator (case, structure, substitution, byte-math, memory, reject, class-based) and every John-native operator, grouped by category in the add-step menu. |
| **Step chain** | Drag, or use the arrow buttons / `Alt+↑`/`Alt+↓`, to reorder steps and watch the output change — the core lesson: order changes the result. Deletes are undoable (`Ctrl+Z`). |
| **Rule line** | The chain as plain text, two-way synced: paste or type a rule to load it into the chain, or edit the chain and watch the line update. |
| **Step-by-step trace** | The word after each step, with the changed part highlighted (color **and** underline, not color alone). Hovering a step, trace row, or rule-line token links all three. |
| **Batch test** | Run the chain against a whole word list at once, with per-row trace buttons back to the full breakdown. |
| **Cheat sheet** | Every operator's syntax plus a clickable, live-generated example. Searchable, filterable to "operators only." |
| **Rulefile validator** | Paste an existing `.rule` file and get a real per-line parse (not a guess) — status, live preview, inline fixes, delete/restore, and a cleaned-file export. |
| **Accessibility** | WCAG 2.2 AA in both themes, AAA in High Contrast mode (auto-detected or manual). Full keyboard support, skip links, and screen-reader announcements for every action. |
| **Display options** | Dark/Light/Auto theme, three text sizes, and separate toggles for hover-linking and auto-scroll — all remembered per browser. |

Press **`?`** (or the **Help** button) any time for the full keyboard/mouse/accessibility reference.

## Hashcat ↔ John the Ripper compatibility

Hashcat's rule engine and John's overlap, but neither is a subset of the
other. A three-way **Target** switch controls which syntax you're building:

| Target | Operators shown | What it's for |
|---|---|---|
| **Hashcat** (default) | All 70 | The unambiguous, de facto standard — what most public rule lists use. The 14 hashcat-only operators are tagged `[Hashcat only]` inline. |
| **Both (hashcat-compatible)** | 56 shared | Only operators John's hashcat-compat mode (`!! hashcat logic ON`) can also build. Checks the *actual* result through both engines and flags it when they diverge for the current word — "buildable in both" isn't always "identical." |
| **John (native rules)** | 56 shared + 21 John-only | John's own syntax, for the things hashcat genuinely can't express (pluralization, whole-word keyboard shift, John's own character classes, and more). |

A **Native compatibility** reference (Section 06's cheat sheet) goes a level
deeper: of the 56 operators shared with John's *native* syntax — no
compat-mode wrapper — it shows exactly which are byte-for-byte identical,
which only diverge on a rare edge case, and which genuinely differ, each
with a worked example verified against both tools' real binaries.

Every chain step keeps its own compatibility badge regardless of which
target you're viewing, so switching target never silently breaks a step
you've already built.

<details>
<summary><b>Exact operator lists and dialect gotchas</b></summary>

- **14 hashcat-only operators** (no John equivalent at all): `3`, `B`, `h`,
  `H`, `v`, and the nine `~`-class operators.
- **21 John-only operators** (no hashcat equivalent at all): pluralize /
  past-tense / -ing-form (3), whole-string insert, early length-limit reject
  (2), UTF-8 validity reject, per-position keyboard-shift, set-a-variable,
  vowel/consonant swap, whole-word keyboard-shift (2), and John's own
  non-`~` character classes (9).
- **Same letter, different meaning.** `p`, `R`, `L`, `v`, `+`, `-` mean
  different things in hashcat syntax vs. John's native grammar. John itself
  resolves `p`/`R`/`L` by whether a digit follows (`p2`/`R2` → hashcat's
  dup-word/bitshift; bare `p`/`R` → John's own pluralize/keyboard-shift) —
  this tool's John-native parser follows the same rule. This ambiguity is
  also why the rulefile validator can't auto-detect a pasted file's
  dialect — you have to say which one.
- **Named positions.** A position argument also accepts John's own
  `z m l # @ $ * - +` in place of a number, both in the rule line and in a
  step's own argument box.
- **"Buildable in both" ≠ "identical."** A handful of the 56 shared
  operators — length rejects, `X`, `3`, `e`, and `R`/`L`'s own CPU-vs-kernel
  split in hashcat — read some words differently even in hashcat-compat
  mode. The Both view catches this live by running the word through both
  engines, not by asserting portability from the list alone.
- **Reference-only.** A few John features are documented but out of scope
  for this tool to build: using a user-defined variable as a position, the
  target-format-dependent line-level reject flags, and single-crack
  word-pair commands. See the comments above `JOHN_ONLY` in `index.html`
  for why each one is excluded.

</details>

## How this was verified

Nothing here is asserted from memory. Hashcat semantics were checked against
hashcat's own `docs/rules.txt`, `src/rp_cpu.c`, and test suite
(`tools/rules-test-cases.yaml`). John semantics were checked against
`doc/RULES`, `doc/RULES-hashcat`, and `src/rules.c` — and, where John's
engine actually *runs* (not just parses), against real `john` and `hashcat`
binaries built from this project's own checkouts, not assumed from an older
release. (That re-check found and fixed a real bug: John's own length ceiling
grew from 128 to 320 bytes in a late-2025 update, and this tool's engine port
had quietly kept truncating at the old limit.)

<details>
<summary><b>Byte semantics and worked examples</b></summary>

- Words run as their UTF-8 bytes, exactly as hashcat does — `é` is two
  bytes, and positions/lengths count bytes, not characters.
- Case operators change only ASCII letters; a half-deleted multi-byte
  character shows as `\xNN`.
- Positions are 0-indexed. Most positional operators silently no-op when a
  position is out of range; a handful (memory extraction, some reject
  filters) reject the whole candidate instead.
- John-native results were checked against the worked examples in John's
  own `doc/RULES` — `Crack96` → `cRACK(^` / `CRaCK96` / `Vtsvl07` / `Xeaxj85`
  for `S`/`V`/`R`/`L` — and against a one-off differential fuzzer run
  against the real `john` binary.

</details>

See [`tests/README.md`](tests/README.md) for how the automated test suite
checks all of this on every run.

## Usage

Open `index.html` directly in a browser, or serve it statically:

```sh
python3 -m http.server 8000
```

Then visit `http://localhost:8000/`. No build step, no dependencies — it's
a single self-contained HTML file.

## Tests

```sh
python3 tests/run_tests.py   # the rule engine in isolation
python3 tests/test_ui.py     # the same rule-handling, driven through the actual UI
```

Neither reimplements the engine's rules in Python — both check that this
project's own engine agrees with an external, independently-computed source.
Details: [`tests/README.md`](tests/README.md).

## License

[MIT](LICENSE) — update the copyright line in `LICENSE` with your own name
or handle before publishing.
