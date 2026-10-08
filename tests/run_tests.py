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
        var rule = arguments[0], word = arguments[1], parseFn = arguments[2], dialect = arguments[3];
        var T = window.__test;
        T.setTarget(dialect === 'hashcat' ? 'hashcat' : 'john_native');
        var parsed = T[parseFn](rule, T.mkStep);
        if (parsed.errors.length) return {error: parsed.errors.join('; ')};
        var result = T.runChain(word, parsed.steps);
        return {rejected: result.rejected, final: result.rejected ? null : result.final};
        """,
        rule, word, parse_fn, dialect,
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

    # Hashcat-only ops (the 14 in JOHN_UNSUPPORTED) must have no John token.
    check(
        "hashcat-only op 'h' (to_hex_lower) has no John token",
        "return window.__test.johnToken('to_hex_lower', {}) === null;",
    )
    check(
        "hashcat-only op 'v' (insert_every) has no John token — John reads v as assign-a-variable in every mode",
        "return window.__test.johnToken('insert_every', {N:4, X:'-'}) === null;",
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


def run_regression_checks(driver, results):
    """Cases found by diffing the tool against real hashcat (3NX, YN) and by
    reading hashcat's rp_cpu.c / John's rules.c (%NX count semantics:
    reject when fewer than N matches; hashcat also rejects when N >= length)."""
    cases = [
        ('hashcat', '30a', 'aaaa', 'aAaa'),             # next char may itself be X
        ('hashcat', '32s', 'mississippi', 'missisSippi'),
        ('hashcat', 'Y0', 'ab', 'ab'),                  # N=0 duplicates nothing
        ('hashcat', 'Y2', 'abc', 'abcbc'),
        ('hashcat', '%2a', 'abab', 'abab'),             # exactly N matches: kept
        ('hashcat', '%3a', 'banana', 'banana'),
        ('hashcat', '%4a', 'banana', None),             # only 3: rejected
        ('hashcat', '~%2?d', 'a1b2', 'a1b2'),
        ('hashcat', '~%3?d', 'a1b2', None),
        ('john', '%2?v', 'aeb', 'aeb'),
        ('john', '%3?v', 'aeb', None),
        ('hashcat', '~@?s', 'caf\u00e9 a-b!', 'caf\u00e9ab'),
        # words are run as UTF-8 bytes: case ops touch ASCII only, lengths and positions count bytes
        ('hashcat', 'u', 'caf\u00e9', 'CAF\u00e9'),
        ('hashcat', 'l', '\u00c9COLE', '\u00c9cole'),
        ('hashcat', '>3', '\u00e9', None),              # \u00e9 is 2 bytes
        ('hashcat', '>2', '\u00e9', '\u00e9'),
        ('hashcat', 'h', '\u00e9', 'c3a9'),
        ('hashcat', '[', '\u00e9a', '\\xA9a'),         # half a character shows as \xNN   # ?s is printable-ASCII symbols (space included), not é
        # \xNN byte escapes in arguments (checked against real hashcat)
        ('hashcat', '$\\xc2 $\\xb5', 'ab', 'abµ'),
        ('hashcat', '^\\xb5 ^\\xc2', 'ab', 'µab'),
        ('hashcat', 'i1\\xc3 i2\\xa9', 'ab', 'aéb'),
        ('hashcat', 'o1\\xc3 o2\\xa9', 'abcd', 'aéd'),
        ('hashcat', '$\\xc5 $\\x8d', 'ab', 'ab\u014d'),
        ('hashcat', '$\\x41', 'ab', 'abA'),
        ('hashcat', 's\\xc3\\xa9', 'café', 'caf\\xA9\\xA9'),   # replaces the first byte of é
        ('john', '$\\xc2 $\\xb5', 'ab', 'abµ'),
        # hashcat's 256-byte buffer: a growing operation that would pass 255 bytes does nothing
        ('hashcat', 'd', 'a' * 128, 'a' * 128),
        ('hashcat', 'd', 'a' * 127, 'a' * 254),
        ('hashcat', '$x', 'a' * 255, 'a' * 255),
        ('hashcat', '$x', 'a' * 254, 'a' * 254 + 'x'),
        ('hashcat', 'p2', 'a' * 100, 'a' * 100),
        ('hashcat', 'h', 'a' * 128, 'a' * 128),
        # the CPU engine (memory, reject and p-position rules), checked against hashcat -a 1 -j
        ('hashcat', '/a Dp', 'banana', 'bnana'),
        ('hashcat', '/a Dp', 'Password1', 'Pssword1'),
        ('hashcat', '/a Dp', 'hello world', None),
        ('hashcat', '%2a Tp', 'banana', 'banAna'),
        ('hashcat', 'M X012 4', 'banana', 'babnanabnanaa'),
        ('hashcat', 'M X012 X012', 'banana', 'babbnana'),     # X reuses the memory buffer as scratch
        ('hashcat', 'M 30a', 'aaaa', 'aaaa'),                 # the CPU engine's 3 differs from the kernel's
    ]
    for dialect, rule, word, want in cases:
        r = run_rule(driver, dialect, rule, word)
        got = r.get('final') if not r.get('error') and not r.get('rejected') else None
        ok = (got == want) and not r.get('error')
        results.append((ok, f'regression [{dialect}] {rule} on {word}', None if ok else f'got {r}, want {want}'))
    # a typed multi-byte character is written one operation per byte, so it works on every hashcat
    for kind, args, want in (('append', "{X:'\u00b5'}", '$\\xc2$\\xb5'), ('prepend', "{X:'\u00b5'}", '^\\xb5^\\xc2'),
                             ('insert', "{N:1,X:'\u00e9'}", 'i1\\xc3i2\\xa9'), ('overstrike', "{N:1,X:'\u00e9'}", 'o1\\xc3o2\\xa9')):
        got = driver.execute_script(f"return window.__test.hashcatToken('{kind}', {args});")
        results.append((got == want, f'regression token for {kind} of a multi-byte character', None if got == want else f'got {got!r}, want {want!r}'))
    # operators that take one byte refuse a raw multi-byte character (hashcat would read half of it)
    for rule in ('s\u00e9a', '@\u00e9', '!\u00e9'):
        r = run_rule(driver, 'hashcat', rule, 'abc')
        results.append((bool(r.get('error')), f'regression [hashcat] {rule} is a syntax error (one byte only)', None if r.get('error') else f'parsed: {r}'))
    # hashcat's class ops accept only ?l ?u ?d ?s ?h ?H; real hashcat refuses ?a / ?b
    for rule in ('~s?a4', '~@?b', '~!?a'):
        r = run_rule(driver, 'hashcat', rule, 'ab1')
        results.append((bool(r.get('error')), f'regression [hashcat] {rule} is a syntax error', None if r.get('error') else f'parsed: {r}'))
    run_john_engine_checks(driver, results)


def run_john_engine_checks(driver, results):
    """A direct port of John the Ripper jumbo's rules_apply() (src/rules.c), built against a real
    `john` binary built from the exact 1.9.0-jumbo-1+bleeding-302f52709 (2026-09-30) checkout in
    john/ (this tool previously targeted the older, pre-built 1.9.0-jumbo-1 (2021-11-02) release;
    re-verifying against the current checkout found a genuine gap — see RULE_WORD_SIZE below —
    since fixed). Checked against the real `john` binary via a differential fuzzer (not checked
    in); these are the specific bugs that fuzzing found, kept as a permanent regression check."""
    def jrun(rule, word, hc=False, min_len=0, max_len=28):
        return driver.execute_script(
            "var r = window.__test.jRulesApply(arguments[0], window.__test.toBytes(arguments[1]),"
            " {hc: arguments[2], minLen: arguments[3], maxLen: arguments[4]});"
            "return r.rc === 0 ? window.__test.fromBytes(r.word) : r.rc;",
            rule, word, hc, min_len, max_len)
    J_RC_REJECT, J_RC_SYNTAX, J_RC_LENGTH = 1, 2, 3   # 3: rejected only by the final Min/Max-length check
    cases = [
        # RULE_WORD_SIZE is 320 as of the Nov 2025 "lengths beyond 128" rework (was 128/0x80 before
        # it) — found by a boundary-focused differential fuzz run (721 disagreements, all of them
        # this tool's own engine truncating every op's output at 127 bytes where real John now
        # allows up to 319) after this tool was re-targeted to the current john/ checkout.
        ('M 46', 'abcdefghijklmnopqrstuvwxyz', 0, 28, J_RC_LENGTH),   # tripled = 78 bytes > max-length 28
        ('M 46', 'abc', 0, 28, 'abcabcabc'),
        # 'z' (a position/length argument) is the symbolic "infinite" length: MAX_PLAINTEXT_LENGTH*2
        # = (320-1)*2 = 638 as of the same rework (was 255/0xFF before it) — either way this exceeds
        # max-length 28, so the expected outcome here doesn't change, only the internal constant.
        ('Zz', 'a', 0, 28, J_RC_LENGTH),    # Z has no overflow guard at all; length grows by 638
        ('Y9', 'ab', 0, 28, 'ab'),           # Y does guard (n <= length): 9 > 2, so unlike Z this is a no-op
        ('Y2', 'ab', 0, 28, 'abab'),         # an in-range N duplicates the last N chars, appended once
        # 'v' writes into rules_vars[], unsigned char in the old release (so a negative N-M wraps
        # mod 256) and plain int in the current one (so it's a real negative) — verified this
        # doesn't actually change any observable outcome: every op that reads a position back out
        # does so into an unsigned int, so a genuine -1 and a wrapped 255 both end up reinterpreted
        # as a huge unsigned value at the point of use either way. va01 sets a = 0-1; ">a" then
        # rejects unless length > a, and does with either representation of "a".
        ('va01 >a', 'abcdefghijklm', 0, 28, J_RC_REJECT),
        ('Ta', 'ab', 0, 28, J_RC_SYNTAX),   # 'a' unset (no prior 'v'): a real syntax error, same as hashcat's p
        # John strips ':'/' '/'\t' out of a rule once, at load time, via a dry run of this same
        # interpreter with reject turned off — a space swallowed as another command's argument
        # survives that pass, but a stray one does not, so "L 6" normalizes to "L6" before it
        # ever runs: the digit right after L, which native mode reads as hashcat's bit-shift-left
        ('L 6', 'ab', 0, 28, 'ab'),
        ('L6', 'ab', 0, 28, 'ab'),
        ('e f', 'a', 0, 28, 'AA'),     # space not swallowed here: 'e' takes its own separator, then f (reflect) runs
        ('ef', 'a', 0, 28, 'A'),       # no space: 'f' is swallowed as e's separator argument instead
        ('R0', 'abcd', 0, 28, '0bcd'),   # a logical (unsigned) shift: John does not sign-extend as hashcat's CPU engine does
        ('M 46', 'abc', 0, 28, 'abcabcabc'),         # fits within 28 bytes: not rejected
        ('d', 'a' * 20, 0, 28, J_RC_LENGTH),         # doubled = 40 bytes, over the 28-byte limit: the *finished* rule is checked
        ('d l', 'a' * 15, 0, 28, J_RC_LENGTH),         # the length check is on the finished rule's output, not per-step
        # RULE_WORD_SIZE regression: a 150-byte word must come through whole (given enough Min/Max
        # length room) — not silently cut to 127 bytes by a stale internal buffer-size constant.
        ('l', 'x' * 150, 0, 200, 'x' * 150),
        # the line-level reject flags this tool can evaluate without target-format context (probed
        # against a real `john --stdout` run): -: -c -8 -S -u pass through; -s -p -R -U always
        # reject; ->N / -<N compare N against the Min/Max length fields.
        ('-: l', 'ABC', 0, 28, 'abc'), ('-c l', 'ABC', 0, 28, 'abc'), ('-8 l', 'ABC', 0, 28, 'abc'),
        ('-S l', 'ABC', 0, 28, 'abc'), ('-u l', 'ABC', 0, 28, 'abc'),
        ('-s l', 'ABC', 0, 28, J_RC_REJECT), ('-p l', 'ABC', 0, 28, J_RC_REJECT),
        ('-R l', 'ABC', 0, 28, J_RC_REJECT), ('-U l', 'ABC', 0, 28, J_RC_REJECT),
        ('->3 l', 'ABC', 0, 28, 'abc'), ('->U l', 'ABC', 0, 28, J_RC_REJECT),   # U = 30 > max-length 28
        ('-<3 l', 'ABC', 0, 28, 'abc'), ('-<Z l', 'ABC', 0, 28, 'abc'),         # min-length 0: -< almost never rejects
        ('-x l', 'ABC', 0, 28, J_RC_SYNTAX),   # not a recognized flag
    ]
    for rule, word, min_len, max_len, want in cases:
        got = jrun(rule, word, False, min_len, max_len)
        ok = got == want
        results.append((ok, f'regression [john] {rule!r} on {word!r}', None if ok else f'got {got!r}, want {want!r}'))
    # under "!! hashcat logic ON" John skips its own rule preprocessor entirely, so \xNN (which
    # that preprocessor is what decodes) is never resolved there — the literal backslash is read
    # as hashcat would read it (a value byte), which real john confirms is a genuine syntax error
    for rule, word, want in (('$\\xc5 $\\x8d', 'ab', J_RC_SYNTAX),):
        got = jrun(rule, word, True, 0, 28)
        ok = got == want
        results.append((ok, f'regression [john hc] {rule!r} on {word!r}', None if ok else f'got {got!r}, want {want!r}'))
    # John's own named positions (z/m/l/#/@/$/*/-/+), now accepted by the rule-line parser too
    for rule, word, min_len, max_len, want in (
        ('Zz', 'a', 0, 28, J_RC_REJECT),      # same bug as above, reached via the real parser this time
        ("'l", 'hello', 0, 28, 'hello'),      # truncate-at-length(l) is a no-op: l is already the length
        ('@?z', 'abc123', 0, 28, J_RC_REJECT),  # z ("all characters") is a complement: Z is the one
        ('@?Z', 'abc123', 0, 28, 'abc123'),     # defined directly, as empty, so z ends up matching everything
        ('@?y', 'abc123', 0, 28, J_RC_REJECT),  # same relationship for y ("valid") / Y
        ('@?Y', 'abc123', 0, 28, 'abc123'),
        ('@?D', 'a1b2', 0, 28, '12'),           # the general case, not just y/z: ?D is "not a digit"
        ('@?d', 'a1b2', 0, 28, 'ab'),
    ):
        got = driver.execute_script(
            "var T=window.__test; T.setTarget('john_native');"
            "var p=T.parseRuleLineJohn(arguments[0],T.mkStep); if(p.errors.length) return 'PARSE_ERROR:'+p.errors.join(';');"
            "var r=T.runChain(arguments[1],p.steps); return r.rejected?1:r.final;",
            rule, word)
        ok = got == want
        results.append((ok, f'regression [john] named position in {rule!r} on {word!r}', None if ok else f'got {got!r}, want {want!r}'))
    # the doc/RULES worked examples, run straight through jRulesApply (independent of the per-op JS)
    for rule, word, want in (('S', 'Crack96', 'cRACK(^'), ('V', 'Crack96', 'CRaCK96'),
                              ('R', 'Crack96', 'Vtsvl07'), ('L', 'Crack96', 'Xeaxj85'),
                              ('p', 'crack', 'cracks'), ('P', 'crack', 'cracked'), ('I', 'crack', 'cracking')):
        got = jrun(rule, word)
        ok = got == want
        results.append((ok, f'regression [john] doc example {rule!r} on {word!r}', None if ok else f'got {got!r}, want {want!r}'))


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
        run_regression_checks(driver, results)
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
