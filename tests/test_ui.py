#!/usr/bin/env python3
"""
Integration tests for the core rule-handling path as driven through the
actual UI, in both views — not just the engine functions in isolation
(that's tests/run_tests.py), but whether building/loading/validating a
rule chain *through the page itself* produces the result the engine
would independently predict for the same steps.

Covers (per the project's own priority: rule-handling correctness first,
everything cosmetic second):

  Chain builder view
    - adding steps via the dropdown + arg inputs updates the trace's
      final result and the exported rule line to match what the engine
      itself computes for that exact step list
    - typing a raw rule line (section 02) round-trips through the parser
      into the chain and back out through the trace/export, in both the
      hashcat and John-native dialects
    - a reject step actually marks the candidate as rejected end-to-end

  Rulefile validator view
    - a pasted multi-line file is classified (comment/blank/rule) and
      parsed correctly, with each valid row's preview matching the
      engine's own result for the same word
    - delete/restore and the exported cleaned file agree with what was
      actually deleted
    - the "Fix in builder" round trip actually rewrites the right row

Each check computes its OWN expected value independently (via
window.__test, the same hook tests/run_tests.py uses) from what was
actually clicked/typed — it does not read a value back from the page
and compare it to itself.

Usage:
    python3 tests/test_ui.py
"""
import sys
import time

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from helpers import make_driver, INDEX_URL, Results  # noqa: E402

# ruleTextInput and validatorInput both debounce their re-parse by 300ms
# (see loadRuleText / reparseValidatorAll in index.html) — any check that
# reads state derived from one of these must wait past that first.
DEBOUNCE_WAIT = 0.4


def set_value(driver, el, value, debounced=False):
    """Set an <input>/<textarea>'s value via JS and fire a real 'input'
    event, the same signal the page's own listeners wait for. Pass
    debounced=True for ruleTextInput/validatorInput, whose handlers
    don't run synchronously on that event."""
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
        el, value,
    )
    if debounced:
        time.sleep(DEBOUNCE_WAIT)


def clear_chain(driver):
    driver.execute_script(
        "while (document.querySelectorAll('.step .del').length) {"
        "  document.querySelector('.step .del').click();"
        "}"
    )


def add_step(driver, op_key, args=None):
    """Adds one step via the real add-step dropdown + button, then fills
    in any arg inputs on the newly-added (last) row."""
    driver.execute_script(
        "document.getElementById('addType').value = arguments[0];"
        "document.getElementById('addBtn').click();",
        op_key,
    )
    if args:
        for name, value in args.items():
            driver.execute_script(
                """
                var rows = document.querySelectorAll('.step');
                var row = rows[rows.length - 1];
                var input = row.querySelector('[data-arg="' + arguments[0] + '"]');
                input.value = arguments[1];
                input.dispatchEvent(new Event('input', {bubbles: true}));
                """,
                name, value,
            )


def engine_token(driver, dialect, op_key, args):
    fn = 'hashcatToken' if dialect == 'hashcat' else 'johnToken'
    return driver.execute_script(
        f"return window.__test.{fn}(arguments[0], arguments[1]);", op_key, args
    )


def engine_run(driver, word, steps):
    """steps: list of (op_key, args) — builds real step objects via
    window.__test.mkStep and runs them through the real runChain."""
    return driver.execute_script(
        """
        var word = arguments[0], specs = arguments[1];
        var T = window.__test;
        var stepList = specs.map(function(s){ return T.mkStep(s[0], s[1]); });
        return T.runChain(word, stepList);
        """,
        word, [[k, a] for k, a in steps],
    )


def final_trace_word(driver):
    return driver.execute_script(
        "var rows = document.querySelectorAll('#trace .trace-row');"
        "return rows[rows.length-1].querySelector('.word').textContent;"
    )


def test_chain_builder_matches_engine(driver, r):
    clear_chain(driver)
    add_step(driver, 'lrest')
    add_step(driver, 'replace', {'X': 'a', 'Y': '4'})
    set_value(driver, driver.find_element('id', 'wordInput'), 'Password')

    expected = engine_run(driver, 'Password', [('lrest', {}), ('replace', {'X': 'a', 'Y': '4'})])
    r.check(not expected['rejected'], 'sanity: l + sa4 on Password should not reject')
    r.check(expected['final'] == 'p4ssword', 'sanity: engine predicts p4ssword', expected['final'])

    ui_final = final_trace_word(driver)
    r.check(ui_final == expected['final'],
            'chain builder trace shows the engine-predicted final word',
            f"UI showed {ui_final!r}, engine predicts {expected['final']!r}")

    expected_tokens = ' '.join([
        engine_token(driver, 'hashcat', 'lrest', {}),
        engine_token(driver, 'hashcat', 'replace', {'X': 'a', 'Y': '4'}),
    ])
    ui_export = driver.execute_script("return document.getElementById('hashcatOutput').textContent;")
    r.check(ui_export == expected_tokens,
            'export box matches the engine-built token string',
            f"UI showed {ui_export!r}, expected {expected_tokens!r}")


def test_rule_line_round_trip_hashcat(driver, r):
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3', debounced=True)
    set_value(driver, driver.find_element('id', 'wordInput'), 'crack')

    expected = engine_run(driver, 'crack', [
        ('lrest_ufirst', {}), ('replace', {'X': 'a', 'Y': '4'}), ('replace', {'X': 'e', 'Y': '3'}),
    ])
    ui_final = final_trace_word(driver)
    r.check(ui_final == expected['final'],
            'typing "c sa4 se3" into section 02 produces the engine-predicted result',
            f"UI showed {ui_final!r}, engine predicts {expected['final']!r}")


def test_rule_line_round_trip_john_native(driver, r):
    driver.find_element('css selector', '#targetBtns .tbtn[data-target="john_native"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'p', debounced=True)
    set_value(driver, driver.find_element('id', 'wordInput'), 'crack')

    expected = engine_run(driver, 'crack', [('j_pluralize', {})])
    ui_final = final_trace_word(driver)
    r.check(ui_final == expected['final'] == 'cracks',
            'typing John-native "p" (pluralize) produces the engine-predicted result',
            f"UI showed {ui_final!r}, engine predicts {expected['final']!r}")
    driver.find_element('css selector', '#targetBtns .tbtn[data-target="hashcat"]').click()


def test_reject_step_marks_rejected(driver, r):
    clear_chain(driver)
    add_step(driver, 'reject_less', {'N': '3'})  # hashcat "<3": reject if length > 3
    set_value(driver, driver.find_element('id', 'wordInput'), 'short')

    expected = engine_run(driver, 'short', [('reject_less', {'N': 3})])
    r.check(expected['rejected'], 'sanity: engine predicts "short" (len 5) is rejected by <3')

    rejected_row_present = driver.execute_script(
        "return !!document.querySelector('#trace .trace-row.rejected');"
    )
    r.check(rejected_row_present, 'trace shows a rejected row for a word that fails the reject filter')


def test_validator_classification_and_preview(driver, r):
    driver.find_element('css selector', '.mbtn[data-mode="validator"]').click()
    set_value(driver, driver.find_element('id', 'wordInput'), 'password')

    rulefile = "# demo\nl sa4\nzzz$\n\n<3"
    set_value(driver, driver.find_element('id', 'validatorInput'), rulefile, debounced=True)

    kinds = driver.execute_script(
        "return Array.from(document.querySelectorAll('#validatorBody tr')).map(function(tr){"
        "  return tr.querySelector('.v-comment') ? 'nonrule' : "
        "    (tr.querySelector('.v-status.err') ? 'invalid' : 'valid');"
        "});"
    )
    r.check(kinds == ['nonrule', 'valid', 'invalid', 'nonrule', 'valid'],
            'validator classifies comment/valid/invalid/blank/valid correctly', kinds)

    expected = engine_run(driver, 'password', [('lrest', {}), ('replace', {'X': 'a', 'Y': '4'})])
    preview = driver.execute_script(
        "return document.querySelector('tr[data-idx=\"1\"] .v-preview').textContent;"
    )
    r.check(preview == expected['final'],
            "row 2's preview ('l sa4' on 'password') matches the engine",
            f"UI showed {preview!r}, engine predicts {expected['final']!r}")


def test_validator_delete_and_export(driver, r):
    # continues from the previous test's state (same 5-line file loaded)
    driver.execute_script("document.querySelector('tr[data-idx=\"2\"] .v-del').click();")  # delete 'zzz$'
    exported = driver.execute_script("return document.getElementById('validatorOutput').value;")
    r.check(exported == '# demo\nl sa4\n\n<3',
            'deleting a row removes it from the export while keeping order/comments/blanks',
            repr(exported))


def test_validator_fix_in_builder_round_trip(driver, r):
    # row 2 ('zzz$') is still invalid; send it to the builder and fix it there
    driver.execute_script("document.querySelector('tr[data-idx=\"2\"] .v-fix').click();")

    in_builder = driver.execute_script("return !document.getElementById('builderView').hidden;")
    r.check(in_builder, '"Fix in builder" switches to the chain builder view')
    rule_text = driver.execute_script("return document.getElementById('ruleTextInput').value;")
    r.check(rule_text == 'zzz$', 'the broken row\'s raw text is loaded into section 02', rule_text)

    # Replace it with something valid, then save & return.
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'l', debounced=True)
    driver.find_element('id', 'validatorReturnSave').click()

    back_in_validator = driver.execute_script("return !document.getElementById('validatorView').hidden;")
    r.check(back_in_validator, '"Save fix & return" switches back to the validator view')
    row_value = driver.execute_script(
        "return document.querySelector('tr[data-idx=\"2\"] .v-rule').value;"
    )
    r.check(row_value == 'l', 'the fixed rule was written back into the right row', row_value)
    row_status = driver.execute_script(
        "return !!document.querySelector('tr[data-idx=\"2\"] .v-status.ok');"
    )
    r.check(row_status, 'that row now shows as valid after the fix')


def main():
    r = Results()
    driver = make_driver()
    try:
        driver.get(INDEX_URL)
        if not driver.execute_script('return !!window.__test'):
            print('FATAL: window.__test hook not found on the page.')
            return 1

        test_chain_builder_matches_engine(driver, r)
        test_rule_line_round_trip_hashcat(driver, r)
        test_rule_line_round_trip_john_native(driver, r)
        test_reject_step_marks_rejected(driver, r)
        test_validator_classification_and_preview(driver, r)
        test_validator_delete_and_export(driver, r)
        test_validator_fix_in_builder_round_trip(driver, r)
    finally:
        driver.quit()

    return r.summarize()


if __name__ == '__main__':
    sys.exit(main())
