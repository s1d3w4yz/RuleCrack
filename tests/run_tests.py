#!/usr/bin/env python3
"""
Automated tests for Password Cracking Rule Chain Lab's rule-handling engine (parsing,
tokenizing, and running hashcat/John rule chains).

This does NOT re-implement the engine or guess expected output — every
test vector comes from an external, authoritative source:
  - tests/fixtures/hashcat_rules_test_cases.json is ported directly from
    hashcat's own tools/rules-test-cases.yaml (the expected_cpu column),
    the same file hashcat's own test suite checks its C/OpenCL kernels
    against.
  - tests/fixtures/john_native_cases.json comes from the worked examples
    printed in John the Ripper jumbo's doc/RULES.
  - A handful of cross-dialect/ambiguity checks below are asserted
    directly against what's documented in doc/RULES-hashcat (p/R/L
    digit-lookahead) and this project's own compatibility tables
    (JOHN_UNSUPPORTED / johnOnly).

It drives the real page in headless Chromium and calls the same
parser/token/engine functions the UI calls (exposed read-only via
window.__test in index.html) — it is not a reimplementation of the
rule engine in Python, so a bug in the engine itself is exercised the
same way a user's browser would exercise it.

Usage:
    python3 tests/run_tests.py

Requires: selenium, a chromium binary, and a matching chromedriver.
Set CHROME_BIN / CHROMEDRIVER_BIN env vars to override the defaults
below if yours live elsewhere.
"""
import json
import os
import pathlib
import sys

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX_URL = 'file://' + str(ROOT / 'index.html')
CHROME_BIN = os.environ.get('CHROME_BIN', '/usr/bin/chromium')
CHROMEDRIVER_BIN = os.environ.get('CHROMEDRIVER_BIN', '/usr/bin/chromedriver')


def make_driver():
    opts = Options()
    opts.binary_location = CHROME_BIN
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    return webdriver.Chrome(service=Service(executable_path=CHROMEDRIVER_BIN), options=opts)


def run_rule(driver, dialect, rule, word):
    """dialect: 'hashcat' or 'john'. Returns {'error': str} on a parse
    error, or {'rejected': bool, 'final': str|None} on a clean parse."""
    parse_fn = 'parseRuleLine' if dialect == 'hashcat' else 'parseRuleLineJohn'
    return driver.execute_script(
        """
        var rule = arguments[0], word = arguments[1], parseFn = arguments[2];
        var T = window.__test;
        var parsed = T[parseFn](rule, T.mkStep);
        if (parsed.errors.length) return {error: parsed.errors.join('; ')};
        var result = T.runChain(word, parsed.steps);
        return {rejected: result.rejected, final: result.rejected ? null : result.final};
        """,
        rule, word, parse_fn,
    )


def run_fixture_file(driver, path, dialect, results):
    with open(path) as f:
        cases = json.load(f)
    for case in cases:
        rule = case['rule']
        label = f"{dialect} rule {rule!r}" + (f" ({case['source']})" if case.get('source') else '')
        survivors = []
        error = None
        for word in case['words']:
            r = run_rule(driver, dialect, rule, word)
            if 'error' in r:
                error = r['error']
                break
            if not r['rejected']:
                survivors.append(r['final'])
        if error:
            results.append((False, label, f"parse error: {error}"))
        elif survivors != case['expected']:
            results.append((False, label, f"got {survivors!r}, expected {case['expected']!r}"))
        else:
            results.append((True, label, None))


def run_ambiguity_checks(driver, results):
    """A handful of hand-picked checks for behavior that a flat input/
    output fixture doesn't capture well: cross-dialect token availability,
    and John's digit-lookahead disambiguation for p/R/L (doc/RULES-hashcat
    note 3/4 — see README's compatibility section)."""

    def check(label, script, *args):
        ok = driver.execute_script(script, *args)
        results.append((bool(ok), label, None if ok else 'assertion returned false'))

    # Hashcat-only ops (the 13 in JOHN_UNSUPPORTED) must have no John token.
    check(
        "hashcat-only op 'h' (to_hex_lower) has no John token",
        "return window.__test.johnToken('to_hex_lower', {}) === null;",
    )
    check(
        "hashcat-only op 'B' (chr_add) has no John token",
        "return window.__test.johnToken('chr_add', {N:0, X:'a'}) === null;",
    )
    # John-only ops (johnOnly:true) must have no hashcat token.
    check(
        "John-only op 'j_pluralize' has no hashcat token",
        "return window.__test.hashcatToken('j_pluralize', {}) === null;",
    )
    check(
        "John-only op 'j_shift_toggle_at' has no hashcat token",
        "return window.__test.hashcatToken('j_shift_toggle_at', {N:0}) === null;",
    )
    # p/R/L ambiguity: with a digit following, John reads the hashcat
    # meaning (dup-word-N-times / bitshift); with no digit, John's own
    # native meaning (pluralize / keyboard-shift).
    check(
        "John native 'p2' parses as hashcat dup-word-N-times, not pluralize",
        """
        var parsed = window.__test.parseRuleLineJohn('p2', window.__test.mkStep);
        return parsed.errors.length === 0 && parsed.steps.length === 1 && parsed.steps[0].type === 'dupeword_times';
        """,
    )
    check(
        "John native 'p' (no digit) parses as pluralize, not hashcat dup-word",
        """
        var parsed = window.__test.parseRuleLineJohn('p', window.__test.mkStep);
        return parsed.errors.length === 0 && parsed.steps.length === 1 && parsed.steps[0].type === 'j_pluralize';
        """,
    )
    check(
        "John native 'R2' parses as hashcat bitshift-right-at-N, not keyboard-shift",
        """
        var parsed = window.__test.parseRuleLineJohn('R2', window.__test.mkStep);
        return parsed.errors.length === 0 && parsed.steps.length === 1 && parsed.steps[0].type === 'chr_shiftr';
        """,
    )
    check(
        "John native 'R' (no digit) parses as whole-word keyboard-shift-right",
        """
        var parsed = window.__test.parseRuleLineJohn('R', window.__test.mkStep);
        return parsed.errors.length === 0 && parsed.steps.length === 1 && parsed.steps[0].type === 'j_keyboard_right';
        """,
    )


def main():
    results = []  # list of (passed: bool, label: str, detail: str|None)
    driver = make_driver()
    try:
        driver.get(INDEX_URL)
        if not driver.execute_script('return !!window.__test'):
            print('FATAL: window.__test hook not found on the page — is index.html out of date,'
                  ' or did a recent edit remove the hook at the end of the main <script>?')
            return 1

        run_fixture_file(driver, ROOT / 'tests/fixtures/hashcat_rules_test_cases.json', 'hashcat', results)
        run_fixture_file(driver, ROOT / 'tests/fixtures/john_native_cases.json', 'john', results)
        run_ambiguity_checks(driver, results)
    finally:
        driver.quit()

    failed = [r for r in results if not r[0]]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("\nFAILURES:")
        for _, label, detail in failed:
            print(f" - {label}: {detail}")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
