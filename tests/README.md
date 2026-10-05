# Tests

Two scripts, in priority order:

- **`run_tests.py`** — the rule-handling engine itself (parsing,
  tokenizing, running a chain), tested in isolation against external
  ground truth. The highest-value thing to protect, since a bug here
  produces a wrong-but-plausible-looking result rather than an obvious
  crash.
- **`test_ui.py`** — the same rule-handling logic, but exercised *through
  the actual page* in both views (chain builder and rulefile validator),
  confirming the UI wiring around the engine — adding steps, typing a
  rule line, pasting a rulefile, the validator's fix-in-builder round
  trip — doesn't silently diverge from what the engine itself would
  predict for the same input.

## Running

```sh
python3 tests/run_tests.py
python3 tests/test_ui.py
```

Both require `selenium` (`pip install selenium`), a Chromium binary, and
a matching chromedriver. Defaults to `/usr/bin/chromium` and
`/usr/bin/chromedriver`; override with the `CHROME_BIN` /
`CHROMEDRIVER_BIN` environment variables if yours live elsewhere.

Exit code is 0 if everything passes, 1 otherwise, so both are
CI-friendly.

## How it works

Both scripts load `index.html` in headless Chromium and call the same
parser/token/engine functions the UI itself calls — `parseRuleLine`,
`parseRuleLineJohn`, `hashcatToken`, `johnToken`, `runChain`, `mkStep` —
via a small, permanent, read-only hook (`window.__test`) at the end of
the main `<script>`. Neither reimplements any rule semantics in Python:
`run_tests.py`'s expected results come from an external, authoritative
source (see Fixtures, below); `test_ui.py`'s expected results are
computed independently via that same `window.__test` hook from steps it
knows it just added/typed, then compared against what the page's own DOM
shows — never read back from the page and compared to itself.

## Fixtures

- **`fixtures/hashcat_rules_test_cases.json`** — ported from hashcat's
  own [`tools/rules-test-cases.yaml`](https://github.com/hashcat/hashcat/blob/master/tools/rules-test-cases.yaml)
  (the `expected_cpu` column), the same fixture hashcat's own project
  uses to check its C/OpenCL kernels against each other. 68 of its 69
  entries are included; one (`/a op4 %3a op4`) was excluded as a likely
  typo/quirk in hashcat's own file — it doesn't tokenize as valid syntax
  under `docs/rules.txt` or `src/rp_cpu.c` by any reading, and its
  expected output contains literal `4` characters no combination of real
  ops produces from the given inputs. See the comment above `SKIP_RULES`
  in the (uncommitted, one-off) extraction script if this ever needs
  regenerating from a newer hashcat checkout.
- **`fixtures/john_native_cases.json`** — the worked examples printed
  directly in John the Ripper jumbo's `doc/RULES` (the `S`/`V`/`R`/`L`
  "Crack96" → ... examples, and the `p`/`P`/`I` pluralize/past-tense/
  -ing-form examples), each tagged with its source line.

Reject rules are handled the way hashcat's own fixture represents them:
`expected_cpu` lists only the *surviving* outputs, in order, with
rejected candidates simply omitted (not blanked) — the test runner
matches that by filtering, not by positional zip.

## Beyond the fixtures

`run_tests.py` also asserts a handful of things a flat input/output
fixture can't express well — cross-dialect token availability (a
hashcat-only op has no John token and vice versa) and John's
digit-lookahead disambiguation for `p`/`R`/`L` (documented in John's
`doc/RULES-hashcat`): `p2`/`R2` parse as hashcat's dup-word/bitshift
forms, while bare `p`/`R` parse as John's own pluralize/keyboard-shift
forms.

## What `test_ui.py` covers

- **Chain builder**: adding steps via the dropdown + arg inputs produces
  the trace/export the engine predicts for that exact step list; typing
  a raw rule line (section 02) round-trips through the parser into the
  chain and back out through the trace, in both the hashcat and
  John-native dialects; a reject step actually marks the candidate
  rejected in the trace.
- **Rulefile validator**: a pasted multi-line file is classified
  (comment/blank/valid/invalid) correctly and each valid row's preview
  matches the engine's own result for the same word; deleting a row
  removes it from the exported file while preserving order and
  comments/blanks; the "Fix in builder" round trip loads the right raw
  text, switches target to match the validator's dialect, and writes the
  fixed rule back into the right row on "Save & return".

## What's *not* covered yet

Cosmetic/layout behavior fixed over the course of this project —
column-height syncing and its expand/collapse interactions, the theme
toggle, the mode toggle itself, the cheat sheet's click-to-insert — is
currently only verified by ad hoc Selenium scripts written during
development, not checked into either persistent suite. Per this
project's own priority (rule-handling correctness first), that's a
reasonable gap to leave for now rather than a thing both suites quietly
promise to catch.
