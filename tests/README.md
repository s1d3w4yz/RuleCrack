# Tests

Automated checks for the rule-handling engine (parsing, tokenizing, and
running hashcat/John rule chains) — the part of `index.html` most worth
protecting from silent regressions, since a subtle bug there produces a
wrong-but-plausible-looking result rather than an obvious crash.

## Running

```sh
python3 tests/run_tests.py
```

Requires `selenium` (`pip install selenium`), a Chromium binary, and a
matching chromedriver. Defaults to `/usr/bin/chromium` and
`/usr/bin/chromedriver`; override with the `CHROME_BIN` /
`CHROMEDRIVER_BIN` environment variables if yours live elsewhere.

Exit code is 0 if everything passes, 1 otherwise, so it's CI-friendly.

## How it works

`run_tests.py` loads `index.html` in headless Chromium and calls the
same parser/token/engine functions the UI itself calls — `parseRuleLine`,
`parseRuleLineJohn`, `hashcatToken`, `johnToken`, `runChain` — via a
small, permanent, read-only hook (`window.__test`) at the end of the
main `<script>`. It does **not** reimplement any rule semantics in
Python; every expected result comes from an external, authoritative
source, and the test only checks that this project's engine, running in
a real browser, agrees with that source.

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

## What's *not* covered yet

This suite only exercises the rule engine itself. The UI/integration
behavior fixed over the course of this project (column-height syncing
and its expand/collapse interactions, the rulefile validator's
fix-in-builder round trip, the theme toggle, etc.) is currently only
verified by ad hoc Selenium scripts written during development, not
checked into a persistent suite. A reasonable next step if this project
keeps growing.
