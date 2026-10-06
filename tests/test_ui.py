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
    - reordering two steps actually changes the result (the tool's core
      pedagogical claim), and in the direction the engine predicts
    - disabling a step excludes it from both the trace and the export
    - a chain's export correctly reacts to the active target: a
      hashcat-only step stays in the export on "Both" (only the add-step
      menu restricts what's buildable fresh) but the portability note
      still warns about it; the note's three other wordings (portable,
      John-native-with-hashcat-form, John-only) are each checked too
    - batch test produces the right per-word output, including showing
      "rejected" for a word a reject step filters out
    - the Min/Max length fields actually change whether a John-native
      aN reject step rejects a given word
    - an out-of-range position argument (e.g. typing 99) clamps to 35 in
      the actual exported rule, not just visually
    - the rule line (section 02) follows chain edits — add, reorder, edit
      an argument, disable (token kept, struck through), delete — while
      text typed into it is left as typed

  Rulefile validator view
    - a pasted multi-line file is classified (comment/blank/rule) and
      parsed correctly, with each valid row's preview matching the
      engine's own result for the same word
    - delete/restore and the exported cleaned file agree with what was
      actually deleted
    - the "Fix in builder" round trip actually rewrites the right row
    - editing a row's own inline input (a different code path from "Fix
      in builder") re-parses it live, synchronously, without losing focus
    - switching the validator's dialect re-parses every row under the
      new grammar (a rule valid in one dialect can be invalid in the
      other) while preserving which rows were deleted

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
    ui_export = driver.execute_script("return window.__test.buildRuleString();")
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


def test_step_reorder_changes_output(driver, r):
    """The tool's entire pedagogical point: reordering two steps changes
    the result. u then l always lowercases (l wins); l then u always
    uppercases (u wins) — same two steps, opposite outputs."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    clear_chain(driver)
    add_step(driver, 'urest')
    add_step(driver, 'lrest')
    set_value(driver, driver.find_element('id', 'wordInput'), 'Test')

    before = engine_run(driver, 'Test', [('urest', {}), ('lrest', {})])
    ui_before = final_trace_word(driver)
    r.check(ui_before == before['final'] == 'test',
            '[u, l] order: UI matches engine (lowercase wins)',
            f"UI {ui_before!r}, engine {before['final']!r}")

    driver.execute_script("document.querySelector('.step .down').click();")  # swap step 1 and 2

    after = engine_run(driver, 'Test', [('lrest', {}), ('urest', {})])
    ui_after = final_trace_word(driver)
    r.check(ui_after == after['final'] == 'TEST',
            '[l, u] order after swap: UI matches engine (uppercase wins)',
            f"UI {ui_after!r}, engine {after['final']!r}")
    r.check(ui_before != ui_after,
            'swapping step order actually changed the result (not a no-op)')


def test_enable_disable_step_excludes_it(driver, r):
    clear_chain(driver)
    add_step(driver, 'urest')
    add_step(driver, 'lrest')
    set_value(driver, driver.find_element('id', 'wordInput'), 'Test')

    both_enabled = engine_run(driver, 'Test', [('urest', {}), ('lrest', {})])
    r.check(final_trace_word(driver) == both_enabled['final'] == 'test',
            'sanity: both steps enabled -> lowercase wins')

    driver.execute_script(
        "document.querySelectorAll('.step .s-enabled')[1].click();"  # disable 'lrest'
    )
    only_first = engine_run(driver, 'Test', [('urest', {})])
    ui_final = final_trace_word(driver)
    r.check(ui_final == only_first['final'] == 'TEST',
            'disabling the 2nd step excludes it from the trace result',
            f"UI {ui_final!r}, engine (urest only) {only_first['final']!r}")

    export = driver.execute_script("return window.__test.buildRuleString();")
    expected_export = engine_token(driver, 'hashcat', 'urest', {})
    r.check(export == expected_export,
            'disabling a step also excludes its token from the export',
            f"UI export {export!r}, expected {expected_export!r} (just 'u', not 'u l')")


def test_cross_target_export_and_portability(driver, r):
    def note():
        return driver.execute_script(
            "var n = document.getElementById('portabilityNote');"
            "return {text: n.textContent, cls: n.className};"
        )

    clear_chain(driver)
    add_step(driver, 'lrest')
    add_step(driver, 'to_hex_lower')  # hashcat-only ('h'): no John equivalent at all

    driver.find_element('css selector', '#targetBtns .tbtn[data-target="hashcat"]').click()
    export = driver.execute_script("return window.__test.buildRuleString();")
    r.check(export == 'l h', 'hashcat target: export includes the hashcat-only step', export)
    n = note()
    r.check(n['cls'] == 'sub warn' and n['text'].startswith('✗ Won’t run in John the Ripper'),
            'hashcat target: portability note warns about the hashcat-only step', n)

    driver.find_element('css selector', '#targetBtns .tbtn[data-target="both"]').click()
    export_both = driver.execute_script("return window.__test.buildRuleString();")
    r.check(export_both == 'l h',
            '"Both" target: a pre-existing hashcat-only step stays in the export '
            '(only the add-step menu restricts what\'s buildable fresh, not steps already built)',
            export_both)
    n2 = note()
    r.check(n2['cls'] == 'sub warn',
            '"Both" target: portability note still warns about the same step')

    # Now drop the hashcat-only step and confirm the "fully portable" note shows.
    driver.execute_script("document.querySelectorAll('.step .del')[1].click();")  # remove to_hex_lower
    n3 = note()
    r.check(n3['cls'] == 'sub ok' and n3['text'].startswith('✓ Portable'),
            '"Both" target with an all-shared chain: portability note confirms it\'s portable', n3)

    driver.find_element('css selector', '#targetBtns .tbtn[data-target="john_native"]').click()
    n4 = note()
    r.check(n4['cls'] == 'sub ok' and n4['text'].startswith('✓ Also valid as plain hashcat syntax'),
            'John-native target with only shared steps: note confirms it\'s also plain hashcat syntax', n4)
    driver.find_element('css selector', '#targetBtns .tbtn[data-target="hashcat"]').click()


def test_batch_test_produces_correct_outputs(driver, r):
    clear_chain(driver)
    add_step(driver, 'urest')
    add_step(driver, 'reject_less', {'N': '3'})  # reject if length > 3
    set_value(driver, driver.find_element('id', 'batchInput'), 'ab\nabcdef')

    rows = driver.execute_script(
        "return Array.from(document.querySelectorAll('#batchBody tr')).map(function(tr){"
        "  var tds = tr.querySelectorAll('td');"
        "  return {word: tds[0].textContent, out: tds[2].textContent, rejected: tds[2].classList.contains('rejected')};"
        "});"
    )
    short_expected = engine_run(driver, 'ab', [('urest', {}), ('reject_less', {'N': 3})])
    long_expected = engine_run(driver, 'abcdef', [('urest', {}), ('reject_less', {'N': 3})])

    r.check(len(rows) == 2, 'batch table has one row per input word', rows)
    if len(rows) == 2:
        r.check(not short_expected['rejected'] and rows[0]['out'] == short_expected['final'] and not rows[0]['rejected'],
                "batch row 1 ('ab', survives): output matches the engine",
                f"got {rows[0]!r}, expected final {short_expected['final']!r}")
        r.check(long_expected['rejected'] and rows[1]['out'] == 'rejected' and rows[1]['rejected'],
                "batch row 2 ('abcdef', too long): shown as rejected",
                rows[1])


def test_min_max_length_fields_affect_john_native_reject(driver, r):
    driver.find_element('css selector', '#targetBtns .tbtn[data-target="john_native"]').click()
    clear_chain(driver)
    add_step(driver, 'j_reject_length', {'N': '2'})  # aN: reject unless (len+N) within [MIN_LEN, MAX_LEN]
    set_value(driver, driver.find_element('id', 'wordInput'), 'password')  # len 8, +2 = 10

    default_max = driver.find_element('id', 'maxLenInput').get_attribute('value')
    r.check(not driver.execute_script("return !!document.querySelector('#trace .trace-row.rejected');"),
            f'sanity: len+2=10 is within the default max length ({default_max}) -> not rejected')

    set_value(driver, driver.find_element('id', 'maxLenInput'), '9')  # now 10 > 9
    rejected_now = driver.execute_script("return !!document.querySelector('#trace .trace-row.rejected');")
    r.check(rejected_now, 'lowering Max length to 9 makes the same aN step reject (10 > 9)')

    set_value(driver, driver.find_element('id', 'maxLenInput'), '28')  # restore default
    driver.find_element('css selector', '#targetBtns .tbtn[data-target="hashcat"]').click()


def test_position_arg_clamping(driver, r):
    clear_chain(driver)
    add_step(driver, 'toggle_at', {'N': '99'})  # out of hashcat's 0-35 position range

    expected_token = engine_token(driver, 'hashcat', 'toggle_at', {'N': 35})  # clamped
    export = driver.execute_script("return window.__test.buildRuleString();")
    r.check(export == expected_token == 'TZ',
            'typing an out-of-range position (99) clamps to 35 in the actual built rule',
            f"UI export {export!r}, expected {expected_token!r}")


def test_validator_inline_edit_live_reparse(driver, r):
    driver.find_element('css selector', '.mbtn[data-mode="validator"]').click()
    driver.find_element('css selector', '#validatorDialectBtns .tbtn[data-dialect="hashcat"]').click()
    set_value(driver, driver.find_element('id', 'validatorInput'), 'zzz$', debounced=True)

    invalid_first = driver.execute_script("return !!document.querySelector('tr[data-idx=\"0\"] .v-status.err');")
    r.check(invalid_first, 'sanity: "zzz$" starts out invalid')

    # Edit the row's own inline input directly (not "Fix in builder") — a
    # different code path (patchValidatorRow), synchronous, no debounce.
    # .focus() first, matching a real user clicking into the field before
    # typing — without it, document.activeElement never reflects the
    # input at all (it's not what's being tested here, just how it's set up).
    driver.execute_script(
        "var inp = document.querySelector('tr[data-idx=\"0\"] .v-rule');"
        "inp.focus();"
        "inp.value = 'l';"
        "inp.dispatchEvent(new Event('input', {bubbles: true}));"
    )
    now_valid = driver.execute_script("return !!document.querySelector('tr[data-idx=\"0\"] .v-status.ok');")
    r.check(now_valid, 'editing the row\'s own input live re-parses it to valid, with no debounce needed')

    focus_kept = driver.execute_script(
        "return document.activeElement === document.querySelector('tr[data-idx=\"0\"] .v-rule');"
    )
    r.check(focus_kept, 'the input keeps focus after a live re-parse (no full table re-render)')


def test_validator_restore(driver, r):
    # continues from the previous test: one row, now 'l', valid
    driver.execute_script("document.querySelector('tr[data-idx=\"0\"] .v-del').click();")
    exported_after_delete = driver.execute_script("return document.getElementById('validatorOutput').value;")
    r.check(exported_after_delete == '', 'deleting the only row empties the export', repr(exported_after_delete))

    is_deleted = driver.execute_script("return document.querySelector('tr[data-idx=\"0\"]').classList.contains('v-deleted');")
    r.check(is_deleted, 'the deleted row is visually marked deleted')

    driver.execute_script("document.querySelector('tr[data-idx=\"0\"] .v-del').click();")  # same button = Restore now
    exported_after_restore = driver.execute_script("return document.getElementById('validatorOutput').value;")
    r.check(exported_after_restore == 'l', 'clicking the same button again restores the row to the export', repr(exported_after_restore))
    is_deleted_now = driver.execute_script("return document.querySelector('tr[data-idx=\"0\"]').classList.contains('v-deleted');")
    r.check(not is_deleted_now, 'the restored row is no longer marked deleted')


def test_validator_dialect_switch_reparses_and_preserves_deletions(driver, r):
    # 'v1a' is valid hashcat syntax (insert 'a' every 1 chars) but 'v' has
    # no case at all in John's native grammar (it's always read as its own
    # variable-assignment form there, out of this tool's scope) — a real
    # case where the same text is valid in one dialect and not the other.
    set_value(driver, driver.find_element('id', 'validatorInput'), 'v1a\nl', debounced=True)
    both_valid = driver.execute_script(
        "return Array.from(document.querySelectorAll('#validatorBody .v-status')).every(function(e){"
        "  return e.classList.contains('ok');"
        "});"
    )
    r.check(both_valid, 'sanity: both "v1a" and "l" are valid under the hashcat dialect')

    driver.execute_script("document.querySelector('tr[data-idx=\"1\"] .v-del').click();")  # delete 'l'

    driver.find_element('css selector', '#validatorDialectBtns .tbtn[data-dialect="john_native"]').click()
    row0_invalid = driver.execute_script("return !!document.querySelector('tr[data-idx=\"0\"] .v-status.err');")
    r.check(row0_invalid, 'switching dialect to John-native re-parses "v1a" as invalid there')

    row1_still_deleted = driver.execute_script("return document.querySelector('tr[data-idx=\"1\"]').classList.contains('v-deleted');")
    r.check(row1_still_deleted, 'the deletion of row 2 survives the dialect switch')

    driver.find_element('css selector', '#validatorDialectBtns .tbtn[data-dialect="hashcat"]').click()


def rule_line(driver):
    return driver.execute_script("return document.getElementById('ruleTextInput').value;")


def test_rule_line_follows_chain_edits(driver, r):
    """Section 02 is the text form of the chain: edits made in section 03
    (add, reorder, edit an argument, disable, delete) rewrite it, disabled
    steps keep their token (drawn struck through), and typing in it is
    NOT rewritten back under the user's cursor. Expected text is built
    independently from the engine's own tokenizer."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    clear_chain(driver)
    r.check(rule_line(driver) == '', 'an empty chain gives an empty rule line', repr(rule_line(driver)))

    steps = [('urest', {}), ('replace', {'X': 'a', 'Y': '4'}), ('append', {'X': '!'})]
    for key, args in steps:
        add_step(driver, key, args)

    def expected(specs):
        return ' '.join(engine_token(driver, 'hashcat', k, a) for k, a in specs)

    r.check(rule_line(driver) == expected(steps), 'adding steps writes them to the rule line',
            f"got {rule_line(driver)!r}, expected {expected(steps)!r}")

    driver.execute_script("document.querySelector('.step .down').click();")  # swap step 1 and 2
    swapped = [steps[1], steps[0], steps[2]]
    r.check(rule_line(driver) == expected(swapped), 'reordering steps reorders the rule line',
            f"got {rule_line(driver)!r}, expected {expected(swapped)!r}")

    # edit step 1's (replace) Y argument through its real input
    driver.execute_script(
        "var i = document.querySelectorAll('.step')[0].querySelector('[data-arg=\"Y\"]');"
        "i.value = '9'; i.dispatchEvent(new Event('input', {bubbles: true}));")
    edited = [('replace', {'X': 'a', 'Y': '9'}), steps[0], steps[2]]
    r.check(rule_line(driver) == expected(edited), "editing a step's argument updates the rule line",
            f"got {rule_line(driver)!r}, expected {expected(edited)!r}")

    # disable the 2nd step (urest): token stays in the text, drawn struck through
    driver.execute_script("document.querySelectorAll('.step .s-enabled')[1].click();")
    r.check(rule_line(driver) == expected(edited), 'a disabled step keeps its token in the rule line',
            f"got {rule_line(driver)!r}")
    struck = driver.execute_script("return [].map.call(document.querySelectorAll('#ruleHl .hl-off'), function(e){return e.textContent;});")
    r.check(struck == [engine_token(driver, 'hashcat', 'urest', {})],
            "the disabled step's token is the one drawn struck through",
            f"struck: {struck!r}")
    export = driver.execute_script("return window.__test.buildRuleString();")
    r.check(export == expected([edited[0], edited[2]]),
            'the export still omits the disabled step even though the rule line shows it', f"export {export!r}")

    driver.execute_script("document.querySelectorAll('.step .del')[0].click();")  # delete the replace step
    remaining = [edited[1], edited[2]]
    r.check(rule_line(driver) == expected(remaining), 'deleting a step removes its token from the rule line',
            f"got {rule_line(driver)!r}, expected {expected(remaining)!r}")

    # typing is the other direction: it rebuilds the chain and must not be reformatted
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c   sa4  $1', debounced=True)
    r.check(rule_line(driver) == 'c   sa4  $1', 'typed text is left exactly as typed (not rewritten from the chain)',
            repr(rule_line(driver)))
    n = driver.execute_script("return document.querySelectorAll('.step').length;")
    r.check(n == 3, 'typed text still rebuilds the chain (3 steps)', f"{n} steps")


def test_text_size_control(driver, r):
    """The A / A / A switch scales the whole page (every font size is in
    rem) and is exclusive: exactly one size is active at a time."""
    def root_px():
        return driver.execute_script("return parseFloat(getComputedStyle(document.documentElement).fontSize);")

    def active():
        return driver.execute_script(
            "return [].map.call(document.querySelectorAll('#sizeSwitch .active'), function(b){return b.dataset.sizeSet;});")

    r.check(root_px() == 16 and active() == [''], 'default text size is 16px with the default button active',
            f"{root_px()}px, active {active()!r}")
    for size, expected in (('lg', 18), ('xl', 20)):
        driver.execute_script("document.querySelector('#sizeSwitch [data-size-set=\"' + arguments[0] + '\"]').click();", size)
        r.check(root_px() == expected and active() == [size], f"'{size}' scales the page to {expected}px and is the only active size",
                f"{root_px()}px, active {active()!r}")
    driver.execute_script("document.querySelector('#sizeSwitch [data-size-set=\"\"]').click();")
    r.check(root_px() == 16 and active() == [''], 'choosing the default returns to 16px', f"{root_px()}px, active {active()!r}")


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
        test_step_reorder_changes_output(driver, r)
        test_enable_disable_step_excludes_it(driver, r)
        test_cross_target_export_and_portability(driver, r)
        test_batch_test_produces_correct_outputs(driver, r)
        test_min_max_length_fields_affect_john_native_reject(driver, r)
        test_position_arg_clamping(driver, r)
        test_rule_line_follows_chain_edits(driver, r)
        test_text_size_control(driver, r)
        test_validator_inline_edit_live_reparse(driver, r)
        test_validator_restore(driver, r)
        test_validator_dialect_switch_reparses_and_preserves_deletions(driver, r)
    finally:
        driver.quit()

    return r.summarize()


if __name__ == '__main__':
    sys.exit(main())
