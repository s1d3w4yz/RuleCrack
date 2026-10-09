# Tests

Two scripts, in priority order:

| Script | Checks | Why it matters most |
|---|---|---|
| **`run_tests.py`** | The rule engine itself (parsing, tokenizing, running a chain), in isolation against external ground truth. | A bug here produces a wrong-but-plausible result, not an obvious crash — the highest-value thing to protect. |
| **`test_ui.py`** | The same rule-handling logic, exercised *through the actual page* (chain builder + rulefile validator). | Confirms the UI wiring around the engine doesn't silently diverge from what the engine itself predicts. |

## Running

```sh
python3 tests/run_tests.py
python3 tests/test_ui.py
```

Requires `selenium` (`pip install selenium`), a Chromium binary, and a
matching chromedriver — defaults to `/usr/bin/chromium` /
`/usr/bin/chromedriver`, overridable via `CHROME_BIN` / `CHROMEDRIVER_BIN`.
Exit code 0 on success, 1 otherwise (CI-friendly).

## How it works

Both scripts load `index.html` in headless Chromium and call the same
parser/token/engine functions the UI itself calls — `parseRuleLine`,
`parseRuleLineJohn`, `hashcatToken`, `johnToken`, `runChain`, `mkStep` — via
a small, permanent, read-only hook (`window.__test`) at the end of the main
`<script>`.

Neither reimplements any rule semantics in Python:

- `run_tests.py`'s expected results come from an external, authoritative
  source — see **Fixtures** below.
- `test_ui.py`'s expected results are computed independently via that same
  `window.__test` hook, from steps it knows it just added or typed, then
  compared against what the page's own DOM shows. Never read back from the
  page and compared to itself.

## Fixtures

- **`fixtures/hashcat_rules_test_cases.json`** — ported from hashcat's own
  [`tools/rules-test-cases.yaml`](https://github.com/hashcat/hashcat/blob/master/tools/rules-test-cases.yaml)
  (the `expected_cpu` column) — the same fixture hashcat uses to check its
  own C/OpenCL kernels against each other. 68 of 69 entries are included;
  one (`/a op4 %3a op4`) was excluded as a likely typo in hashcat's own
  file — it doesn't tokenize as valid syntax under `docs/rules.txt` or
  `src/rp_cpu.c` by any reading, and its expected output contains literal
  `4` characters no combination of real ops produces from the given inputs.
- **`fixtures/john_native_cases.json`** — the worked examples printed
  directly in John jumbo's `doc/RULES` (the `S`/`V`/`R`/`L` "Crack96"
  examples, and the `p`/`P`/`I` pluralize/past-tense/-ing-form examples),
  each tagged with its source line.

Reject rules follow hashcat's own fixture convention: `expected_cpu` lists
only the *surviving* outputs, in order, with rejected candidates omitted
(not blanked) — the test runner matches by filtering, not positional zip.

> Regenerating from a newer hashcat checkout? See the comment above
> `SKIP_RULES` in the (uncommitted, one-off) extraction script.

## Beyond the fixtures

A flat input/output fixture can't express everything, so `run_tests.py`
also directly asserts:

- **Cross-dialect token availability** — a hashcat-only op has no John
  token and vice versa.
- **John's digit-lookahead disambiguation** for `p`/`R`/`L` (documented in
  `doc/RULES-hashcat`): `p2`/`R2` parse as hashcat's dup-word/bitshift
  forms, while bare `p`/`R` parse as John's own pluralize/keyboard-shift
  forms.

## What `test_ui.py` covers

<details open>
<summary><b>Chain builder</b></summary>

- Adding steps via the dropdown + arg inputs produces the trace/export the
  engine predicts for that exact step list.
- Typing a raw rule line (section 02) round-trips through the parser into
  the chain and back out through the trace, in both dialects.
- A reject step actually marks the candidate rejected in the trace.
- **Reordering two steps actually changes the result** in the direction the
  engine predicts — the tool's core pedagogical claim, otherwise untested.
- The rule line follows chain edits (add, reorder, edit an argument,
  disable, delete), while text typed directly into it is left as typed.
- Disabling a step excludes it from both the trace and the export.
- A chain's export correctly reacts to the active target — e.g. a
  hashcat-only step stays in the export on "Both" (only the add-step menu
  restricts what's buildable fresh) while the portability note still warns
  about it. All four note wordings are checked.
- Batch test produces the right per-word output, including "rejected" rows.
- The Min/Max length fields actually change whether a John-native `aN`
  reject step fires.
- An out-of-range position argument clamps to 35 in the actual exported
  rule, not just visually.

</details>

<details open>
<summary><b>Rulefile validator</b></summary>

- A pasted multi-line file is classified (comment / blank / valid /
  invalid) correctly, and each valid row's preview matches the engine's own
  result for the same word.
- Deleting a row removes it from the exported file while preserving order
  and comments/blanks; the same button restores it.
- The "Fix in builder" round trip loads the right raw text, switches target
  to match the validator's dialect, and writes the fixed rule back into the
  right row on "Save & return."
- Editing a row's own inline input (a separate code path from "Fix in
  builder") re-parses it live without losing focus.
- Switching the validator's dialect re-parses every row under the new
  grammar — the same text can be valid in one dialect and not the other —
  while preserving which rows were deleted.

</details>

## What's *not* covered yet

Cosmetic/layout behavior — column-height syncing and its expand/collapse
interactions, the theme toggle, the mode toggle itself, the cheat sheet's
click-to-insert — is currently only verified by ad hoc Selenium scripts
written during development, not checked into either persistent suite.
Per this project's own priority (rule-handling correctness first), that's a
reasonable gap to leave rather than a thing both suites quietly promise to
catch.
