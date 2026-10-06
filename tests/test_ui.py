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
    - the Auto theme follows the system live, falls back to dark, is
      remembered, and an explicit Dark/Light ignores the system
    - the three columns stay equal height however full the lists are
      (full, one-step and empty chains; expanding a short list), and in a
      tall window they end at column 2's natural height by shrinking the
      chain list instead of padding the trace box; resizing the window
      re-fits them, and the stacked narrow layout falls back to the
      stylesheet caps
    - the page is a real document (standards mode, lang, viewport, one
      <main>, working skip links) and every visible control in both views
      has an accessible name
    - a deleted step can be undone (Undo button, Ctrl+Z), and keyboard
      shortcuts (Alt+Up/Down to move, Delete to remove) work from a step's
      checkbox and buttons but not inside its dropdown or text boxes
    - hovering a token in the rule line (real mouse) links its step card
      and trace row, gaps link nothing, and it still works when the line
      has scrolled sideways
    - with nothing hovered, the text cursor in the rule line links the
      step whose token it is in (arrow keys, selections, typing a token)
    - hovering a trace row lights up its step card and rule-line token
      (the link works from either side)
    - hovering or focusing a step also highlights its row in the trace
      (scrolling it into view), and what changed in the trace is
      underlined as well as colored
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
        "  var out = tr.querySelector('td.out');"
        "  return {word: tr.querySelector('td.b-in').textContent, out: out.textContent, rejected: out.classList.contains('rejected')};"
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


def test_columns_stay_equal_height(driver, r):
    """The three columns of the builder view must end at the same height
    however full the lists are — a short chain, an empty one, a typed rule
    whose status line appears — not only with the default example."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def heights():
        return driver.execute_script(
            "return ['col1Card', 'col2Card', 'cheatCard'].map(function(id){"
            "  return Math.round(document.getElementById(id).getBoundingClientRect().height);});")

    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)
    h = heights()
    r.check(len(set(h)) == 1, 'columns are equal height with a full chain', f'{h}')

    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c', debounced=True)
    h = heights()
    r.check(len(set(h)) == 1, 'columns are equal height with a one-step chain (list shorter than its box)', f'{h}')

    clear_chain(driver)
    time.sleep(0.2)
    h = heights()
    r.check(len(set(h)) == 1, 'columns are equal height with an empty chain', f'{h}')
    shown = driver.execute_script("return !!document.querySelector('#chain .chain-empty');")
    r.check(shown, 'an empty chain shows a hint instead of a blank box')
    add_step(driver, 'lrest')
    gone = driver.execute_script("return !document.querySelector('#chain .chain-empty') && document.querySelectorAll('#chain .step').length === 1;")
    r.check(gone, 'the hint disappears as soon as a step is added')
    clear_chain(driver)
    time.sleep(0.2)

    driver.execute_script("document.getElementById('traceExpandBtn').click();")
    h = heights()
    r.check(len(set(h)) == 1, 'expanding a list that has few rows does not make its column shorter', f'{h}')
    driver.execute_script("document.getElementById('traceExpandBtn').click();")


def test_tall_window_shrinks_chain_instead_of_padding_trace(driver, r):
    """In a window taller than column 2's content needs (e.g. 1215x1123),
    the columns must end at column 2's natural height by SHRINKING the
    step-chain list — not by padding the trace box with empty space to
    reach column 1's height. Runs last: it reloads the page at a different
    viewport size."""
    driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',
                           {'width': 1215, 'height': 1300, 'deviceScaleFactor': 1, 'mobile': False})
    try:
        driver.get(INDEX_URL)
        time.sleep(0.8)
        m = driver.execute_script(
            "var h = function(id){ return Math.round(document.getElementById(id).getBoundingClientRect().height); };"
            "var t = document.getElementById('trace'), c = document.getElementById('chain');"
            "return {c1: h('col1Card'), c2: h('col2Card'), c3: h('cheatCard'), vh: window.innerHeight,"
            "        trace: h('trace'),        traceContent: [].reduce.call(t.children, function(a, e){ return a + e.getBoundingClientRect().height; }, 0) + 2, chain: h('chain'), chainContent: c.scrollHeight + 2};")
        r.check(m['c1'] == m['c2'] == m['c3'], 'tall window: all three columns are equal height', f'{m}')
        r.check(m['trace'] <= m['traceContent'] + 1,
                'tall window: the trace box is not padded past its own rows', f"box {m['trace']}px, content {m['traceContent']}px")
        r.check(m['chain'] < m['chainContent'],
                'tall window: the chain list was shrunk (scrolls) to match column 2', f"box {m['chain']}px, content {m['chainContent']}px")
        r.check(m['c1'] < m['vh'] - 24,
                'tall window: columns end below the viewport limit because column 2 has no more to show', f"{m['c1']}px vs limit {m['vh'] - 24}px")
    finally:
        driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
        driver.get(INDEX_URL)


def test_columns_refit_on_window_resize(driver, r):
    """Resizing the window re-fits the columns (they used to be sized only
    at load), only while the three columns sit side by side; the stacked
    narrow layout falls back to the stylesheet caps and comes back cleanly.
    Runs last: it changes the viewport size."""
    def size(w, h):
        driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',
                               {'width': w, 'height': h, 'deviceScaleFactor': 1, 'mobile': False})
        time.sleep(0.5)  # past the 150ms resize debounce

    def cols():
        return driver.execute_script(
            "var h = function(id){ return Math.round(document.getElementById(id).getBoundingClientRect().height); };"
            "return {c1: h('col1Card'), c2: h('col2Card'), c3: h('cheatCard'), vh: window.innerHeight,"
            "        chain: h('chain'), trace: h('trace')};")

    try:
        size(1500, 857)
        driver.get(INDEX_URL)
        time.sleep(0.8)
        a = cols()
        r.check(a['c1'] == a['c2'] == a['c3'] and a['c1'] <= a['vh'], 'sanity: equal columns that fit at 1500x857', f'{a}')

        size(1500, 1123)
        b = cols()
        r.check(b['c1'] == b['c2'] == b['c3'] and b['c1'] > a['c1'],
                'making the window taller re-fits the columns (equal, and taller than before)', f'{a["c1"]}px -> {b["c1"]}px')

        size(1500, 700)
        c = cols()
        r.check(c['c1'] == c['c2'] == c['c3'] and c['c1'] < b['c1'],
                'making the window shorter re-fits the columns again (equal, and shorter)', f'{b["c1"]}px -> {c["c1"]}px')

        size(1000, 900)
        n = cols()
        r.check(n['chain'] <= 560 and n['trace'] <= 420,
                'in the stacked narrow layout the lists use their stylesheet caps, not the column fit', f'{n}')

        size(1500, 857)
        e = cols()
        r.check(e == a, 'returning to the original size restores the original column heights exactly', f'{a} vs {e}')
    finally:
        driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
        driver.get(INDEX_URL)


ACCESSIBLE_NAME_JS = """
var visible = function(e){ var r = e.getBoundingClientRect(), c = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none' && !e.closest('[hidden]'); };
var text = function(id){ var el = document.getElementById(id); return el ? el.textContent.trim() : ''; };
var nameOf = function(e){
  var lb = e.getAttribute('aria-labelledby');
  if (lb && lb.split(/\\s+/).map(text).join('').length) return 'labelledby';
  if ((e.getAttribute('aria-label') || '').trim()) return 'aria-label';
  if (e.labels && e.labels.length && [].map.call(e.labels, function(l){ return l.textContent; }).join('').trim()) return 'label';
  if (!/^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName) && (e.innerText || '').trim()) return 'content';
  return '';   // a title or placeholder alone is not accepted
};
return [].filter.call(document.querySelectorAll('button, input, select, textarea, a[href]'), visible)
  .filter(function(e){ return !nameOf(e); })
  .map(function(e){ return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className).split(' ')[0]; });
"""


def test_every_control_has_an_accessible_name(driver, r):
    """Every visible button, field, dropdown and link in both views has a
    real accessible name (aria-label / aria-labelledby / <label> / its own
    text) — a title or placeholder alone doesn't count, since screen
    readers don't reliably announce those."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 $1 x14 ~s?ds5', debounced=True)
    unnamed = driver.execute_script(ACCESSIBLE_NAME_JS)
    r.check(not unnamed, 'builder view: every control has an accessible name', f'unnamed: {unnamed}')

    driver.find_element('css selector', '.mbtn[data-mode="validator"]').click()
    set_value(driver, driver.find_element('id', 'validatorInput'), 'c sa4\nzzz\n# a comment\n', debounced=True)
    unnamed = driver.execute_script(ACCESSIBLE_NAME_JS)
    r.check(not unnamed, 'validator view: every control has an accessible name', f'unnamed: {unnamed}')
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()


def test_document_basics(driver, r):
    """The page is a real HTML document: standards mode, a language, a
    viewport tag (so phones don't render it zoomed out), one <main>, and
    working skip links."""
    info = driver.execute_script(
        "return {mode: document.compatMode, lang: document.documentElement.lang,"
        "  viewport: !!document.querySelector('meta[name=viewport]'), charset: document.characterSet,"
        "  mains: document.querySelectorAll('main').length,"
        "  skipTargets: [].map.call(document.querySelectorAll('.skipnav a'), function(a){"
        "    return !!document.getElementById(a.getAttribute('href').slice(1)); })};")
    r.check(info['mode'] == 'CSS1Compat', 'the page renders in standards mode (has a doctype)', f"{info['mode']}")
    r.check(info['lang'] == 'en', 'the page declares its language', f"lang={info['lang']!r}")
    r.check(info['viewport'] and info['charset'] == 'UTF-8', 'viewport meta present and UTF-8 charset', f'{info}')
    r.check(info['mains'] == 1, 'exactly one <main> landmark', f"{info['mains']}")
    r.check(all(info['skipTargets']), 'every skip link points at a real element', f"{info['skipTargets']}")


def test_toggle_groups_expose_pressed_state(driver, r):
    """Mode, target, syntax, theme and text-size switches are groups of
    toggle buttons: exactly one is aria-pressed at a time, it matches the
    visual .active one, and it follows clicks. (They were role=tablist
    without tabs, which assistive tech announces inconsistently.)"""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def state(group):
        return driver.execute_script(
            "var g = document.getElementById(arguments[0]);"
            "return {role: g.getAttribute('role'),"
            "  pressed: [].map.call(g.querySelectorAll('button'), function(b){ return b.getAttribute('aria-pressed'); }),"
            "  active: [].map.call(g.querySelectorAll('button'), function(b){ return b.classList.contains('active') ? 'true' : 'false'; })};",
            group)

    groups = [('modeToggle', 'button[data-mode="validator"]'),
              ('targetBtns', 'button[data-target="john_native"]'),
              ('themeSwitch', 'button[data-theme-set="light"]'),
              ('sizeSwitch', 'button[data-size-set="lg"]')]
    for gid, other in groups:
        st = state(gid)
        r.check(st['role'] == 'group' and st['pressed'].count('true') == 1 and st['pressed'] == st['active'],
                f'#{gid}: a group with exactly one pressed button, matching the visual state', f'{st}')
        driver.execute_script("document.querySelector('#' + arguments[0] + ' ' + arguments[1]).click();", gid, other)
        st2 = state(gid)
        r.check(st2['pressed'].count('true') == 1 and st2['pressed'] == st2['active'] and st2['pressed'] != st['pressed'],
                f'#{gid}: clicking another button moves the pressed state', f'{st} -> {st2}')
    # leave everything as found: builder view, hashcat target, dark theme, default size
    driver.execute_script("document.querySelector('#modeToggle button[data-mode=\"builder\"]').click();"
                          "document.querySelector('#targetBtns button[data-target=\"hashcat\"]').click();"
                          "document.querySelector('#themeSwitch button[data-theme-set=\"dark\"]').click();"
                          "document.querySelector('#sizeSwitch button[data-size-set=\"\"]').click();")
    driver.find_element('css selector', '.mbtn[data-mode="validator"]').click()
    st = state('validatorDialectBtns')
    r.check(st['role'] == 'group' and st['pressed'].count('true') == 1 and st['pressed'] == st['active'],
            '#validatorDialectBtns: a group with exactly one pressed button', f'{st}')
    driver.execute_script("document.querySelector('#validatorDialectBtns button[data-dialect=\"john_native\"]').click();")
    st2 = state('validatorDialectBtns')
    r.check(st2['pressed'] == ['false', 'true'] and st2['active'] == ['false', 'true'], '#validatorDialectBtns: clicking John moves the pressed state', f'{st2}')
    driver.execute_script("document.querySelector('#validatorDialectBtns button[data-dialect=\"hashcat\"]').click();")
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()


def test_live_announcements(driver, r):
    """Changes a screen reader user can't see are announced through the
    hidden #liveStatus region (moves, deletes, copies, the result, search
    counts), the in-place status lines are live regions, and the rule
    line reports aria-invalid while it has parse errors. Nothing is
    announced on page load."""
    def live():
        return driver.execute_script("return document.getElementById('liveStatus').textContent;")

    def settle():
        time.sleep(1.4)  # let any pending debounced announcement fire first

    driver.get(INDEX_URL)
    time.sleep(1.0)
    r.check(live() == '', 'nothing is announced on page load', repr(live()))
    attrs = driver.execute_script(
        "return ['ruleParseStatus', 'portabilityNote', 'validatorSummary', 'targetNote'].map(function(id){"
        "  return document.getElementById(id).getAttribute('aria-live'); });")
    r.check(attrs == ['polite'] * 4, 'status lines that update in place are polite live regions', f'{attrs}')

    settle()
    driver.execute_script("document.querySelectorAll('.step')[1].querySelector('.down').click();")
    time.sleep(0.25)
    r.check(live() == 'Step moved down to position 3 of 8', 'moving a step down announces its new position', repr(live()))

    settle()
    driver.execute_script("document.querySelector('.step .del').click();")
    time.sleep(0.25)
    r.check(live().startswith('Deleted step 1.'), 'deleting a step announces it', repr(live()))

    settle()
    driver.execute_script("document.getElementById('copyRuleBtn').click();")
    time.sleep(0.4)
    r.check(live() == 'Rule copied', 'copying the rule announces it', repr(live()))

    settle()
    set_value(driver, driver.find_element('id', 'wordInput'), 'dragon')
    time.sleep(1.3)
    r.check(live().startswith('Result: '), 'changing the word announces the new result after a pause', repr(live()))

    settle()
    set_value(driver, driver.find_element('id', 'cheatSearch'), 'rev')
    time.sleep(1.0)
    r.check(live() == '2 operators match', 'searching the cheat sheet announces how many operators match', repr(live()))
    set_value(driver, driver.find_element('id', 'cheatSearch'), '')

    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'zzz', debounced=True)
    invalid = driver.execute_script("return document.getElementById('ruleTextInput').getAttribute('aria-invalid');")
    r.check(invalid == 'true', 'a rule line with parse errors is marked aria-invalid', f'{invalid!r}')
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4', debounced=True)
    invalid = driver.execute_script("return document.getElementById('ruleTextInput').getAttribute('aria-invalid');")
    r.check(invalid is None, 'aria-invalid clears once the line parses', f'{invalid!r}')


def test_reduced_motion_is_respected(driver, r):
    """With the system's 'reduce motion' setting on, the batch 'trace'
    jump does not play its flash animation and the page scrolls instantly;
    with it off, both still happen. Runs last (changes media emulation)."""
    def media(value):
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia',
                               {'features': [{'name': 'prefers-reduced-motion', 'value': value}]})

    def probe():
        driver.get(INDEX_URL)
        time.sleep(0.8)
        driver.execute_script("window.scrollTo(0, 0); document.querySelectorAll('.tracebtn')[1].click();")
        time.sleep(0.12)
        early = driver.execute_script("return Math.round(window.scrollY);")
        anim = driver.execute_script("return getComputedStyle(document.getElementById('trace')).animationName;")
        time.sleep(1.0)
        late = driver.execute_script("return Math.round(window.scrollY);")
        return early, late, anim

    try:
        media('no-preference')
        early, late, anim = probe()
        r.check(anim == 'jumpFlash' and early < late, 'normally: the jump flashes and scrolls smoothly',
                f'animation {anim!r}, scrollY {early} -> {late}')
        media('reduce')
        early, late, anim = probe()
        r.check(anim == 'none' and early == late and late > 0, 'with reduce-motion: no flash, and the scroll is instant',
                f'animation {anim!r}, scrollY {early} -> {late}')
    finally:
        media('no-preference')
        driver.get(INDEX_URL)


TARGET_SIZE_JS = """
// a control scrolled out of sight inside a scroll box (the chain/trace/cheat
// lists) can't be clicked, so it isn't a target right now
var clipped = function(e){ var r = e.getBoundingClientRect(), cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
  for (var p = e.parentElement; p; p = p.parentElement){
    var c = getComputedStyle(p);
    if (c.overflowX !== 'visible' || c.overflowY !== 'visible'){
      var b = p.getBoundingClientRect(); if (cx < b.left || cx > b.right || cy < b.top || cy > b.bottom) return true; } }
  return false; };
var vis = function(e){ var r = e.getBoundingClientRect(), c = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none' && !e.closest('[hidden]') && !e.closest('.skipnav') && !clipped(e); };
var all = [].filter.call(document.querySelectorAll('button, input, select, textarea, a[href]'), vis);
// a checkbox inside/with a <label> is also clickable through the label
var rect = function(e){ var r = e.getBoundingClientRect(), L = r;
  if (e.labels && e.labels.length){ var l = [].map.call(e.labels, function(x){ return x.getBoundingClientRect(); }).filter(function(b){ return b.width > 0; })[0];
    if (l) L = {left: Math.min(r.left, l.left), right: Math.max(r.right, l.right), top: Math.min(r.top, l.top), bottom: Math.max(r.bottom, l.bottom)}; }
  return {left: L.left, right: L.right, top: L.top, bottom: L.bottom, w: L.right - L.left, h: L.bottom - L.top}; };
var dist = function(cx, cy, b){ var dx = Math.max(b.left - cx, 0, cx - b.right), dy = Math.max(b.top - cy, 0, cy - b.bottom); return Math.hypot(dx, dy); };
var bad = [];
all.forEach(function(e){
  var b = rect(e); if (b.w >= 24 && b.h >= 24) return;
  // Only native checkboxes may be smaller (a native control can't be padded).
  // They use WCAG 2.2 2.5.8's spacing exception: a 24px circle centered on
  // the target must not touch any other target.
  if (e.type !== 'checkbox'){ bad.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className).split(' ')[0] + ' ' + Math.round(b.w) + 'x' + Math.round(b.h)); return; }
  var cx = (b.left + b.right) / 2, cy = (b.top + b.bottom) / 2;
  var clash = all.some(function(o){ return o !== e && dist(cx, cy, rect(o)) < 12; });
  if (clash) bad.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className).split(' ')[0] + ' ' + Math.round(b.w) + 'x' + Math.round(b.h));
});
return bad;
"""


def test_click_targets_are_big_enough(driver, r):
    """Every visible control is at least 24x24 CSS px (WCAG 2.2 AA, 2.5.8);
    only native checkboxes may be smaller, and only if a 24px circle around
    them touches no other control. Controls scrolled out of sight inside a
    list are skipped."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 $1 x14', debounced=True)
    bad = driver.execute_script(TARGET_SIZE_JS)
    r.check(not bad, 'builder view: no click target is too small', f'too small: {bad}')
    driver.find_element('css selector', '.mbtn[data-mode="validator"]').click()
    set_value(driver, driver.find_element('id', 'validatorInput'), 'c sa4\nzzz\n# a comment\n', debounced=True)
    bad = driver.execute_script(TARGET_SIZE_JS)
    r.check(not bad, 'validator view: no click target is too small', f'too small: {bad}')
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()


def test_compat_operators_have_a_non_color_marker(driver, r):
    """hashcat-only / John-only operators in the cheat sheet are told apart
    by more than color: each such row has a letter tag (HC / J) and a
    spoken prefix, and shared operators carry neither."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    js = ("var rows = [].slice.call(document.querySelectorAll('#cheatBody > .cheat-row'));"
          "var count = function(cls){ var colored = rows.filter(function(x){ return x.querySelector('.syntax.' + cls); });"
          "  return {colored: colored.length,"
          "    tagged: colored.filter(function(x){ return x.querySelector('.desc .mk.' + cls); }).length,"
          "    spoken: colored.filter(function(x){ return /only: /.test((x.querySelector('.desc .sr-only') || {}).textContent || ''); }).length}; };"
          "return {hc: count('tok-hc'), john: count('tok-john'), marks: document.querySelectorAll('#cheatBody .desc .mk').length};")
    for target, key, label in (('hashcat', 'hc', 'HC'), ('john_native', 'john', 'J')):
        driver.execute_script("document.querySelector('#targetBtns [data-target=\"' + arguments[0] + '\"]').click();", target)
        m = driver.execute_script(js)
        c = m[key]
        r.check(c['colored'] > 0 and c['colored'] == c['tagged'] == c['spoken'] and m['marks'] == c['colored'],
                f"{target} tab: every {label}-only operator has the {label} tag and a spoken prefix, and nothing else is tagged", f'{m}')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"both\"]').click();")
    m = driver.execute_script(js)
    r.check(m['marks'] == 0, 'Both tab: no operator is tagged (only shared ones are listed)', f'{m}')
    legend = driver.execute_script("return [].map.call(document.querySelectorAll('.compat-key .mk'), function(x){ return x.textContent; });")
    r.check(legend == ['HC', 'J'], 'the legend shows the same HC and J tags', f'{legend}')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")


def test_delete_can_be_undone(driver, r):
    """Deleting a step shows a toast with Undo; Undo (button or Ctrl+Z)
    restores the same step, with its arguments, at its old position;
    several deletes undo in reverse order; Ctrl+Z inside a text field is
    left to that field; and typing a new rule clears the undo history."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys

    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 $!', debounced=True)

    def chain():
        return driver.execute_script(
            "return [].map.call(document.querySelectorAll('#chain .step'), function(r){"
            "  return r.querySelector('.s-type').value + ':' + [].map.call(r.querySelectorAll('.p-arg'), function(a){ return a.value; }).join(''); });")

    def toast():
        return driver.execute_script("var t = document.getElementById('undoToast'); return t.hidden ? null : t.textContent.replace(/\\s+/g, ' ').trim();")

    original = chain()
    r.check(toast() is None, 'no undo toast before anything is deleted')

    driver.execute_script("document.querySelectorAll('#chain .step .del')[2].click();")   # delete 'se3'
    r.check(len(chain()) == len(original) - 1 and 'Step 3 deleted' in (toast() or ''), 'deleting a step shows an undo toast', f'{toast()!r}')
    driver.find_element('id', 'undoBtn').click()
    r.check(chain() == original, 'the Undo button restores the step at its old position, arguments intact', f'{chain()} vs {original}')
    r.check(toast() is None, 'the toast goes away once there is nothing left to undo', f'{toast()!r}')

    driver.execute_script("document.querySelectorAll('#chain .step .del')[1].click();")   # delete 'sa4'
    driver.execute_script("document.querySelectorAll('#chain .step .del')[1].click();")   # then 'se3'
    r.check(len(chain()) == len(original) - 2 and '2 can be undone' in (toast() or ''), 'two deletes can both be undone', f'{toast()!r}')
    ActionChains(driver).key_down(Keys.CONTROL).send_keys('z').key_up(Keys.CONTROL).perform()
    time.sleep(0.2)
    ActionChains(driver).key_down(Keys.CONTROL).send_keys('z').key_up(Keys.CONTROL).perform()
    time.sleep(0.2)
    r.check(chain() == original, 'Ctrl+Z twice restores both, in reverse order', f'{chain()} vs {original}')

    # Ctrl+Z in a text field must stay that field's own undo
    driver.execute_script("document.querySelectorAll('#chain .step .del')[0].click();")
    rule = driver.find_element('id', 'ruleTextInput')
    rule.click()
    ActionChains(driver).key_down(Keys.CONTROL).send_keys('z').key_up(Keys.CONTROL).perform()
    time.sleep(0.2)
    r.check(len(chain()) == len(original) - 1, 'Ctrl+Z inside the rule line does not restore a deleted step', f'{len(chain())} steps')

    # typing a rule replaces the chain: the history no longer applies
    set_value(driver, rule, 'c sa4', debounced=True)
    r.check(toast() is None, 'typing a new rule clears the undo history and hides the toast', f'{toast()!r}')
    driver.find_element('tag name', 'body').click()
    ActionChains(driver).key_down(Keys.CONTROL).send_keys('z').key_up(Keys.CONTROL).perform()
    time.sleep(0.2)
    r.check(chain() == ['lrest_ufirst:', 'replace:a4'], 'Ctrl+Z after typing a rule restores nothing', f'{chain()}')


def test_page_has_no_phantom_scroll(driver, r):
    """The page ends right after its content (the body's own 12px padding
    and nothing more) in every target and with the cheat sheet expanded.
    Guards against hidden/positioned elements (the screen-reader-only
    spans inside the long cheat list were one) stretching the page with
    blank scroll, which also spoils the 'scroll to the end and the columns
    sit centered' behavior."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def extra():
        return driver.execute_script(
            "return Math.round(document.documentElement.scrollHeight -"
            "  (document.querySelector('.wrap').getBoundingClientRect().bottom + window.scrollY));")

    for target in ('hashcat', 'john_native', 'both'):
        driver.execute_script("document.querySelector('#targetBtns [data-target=\"' + arguments[0] + '\"]').click();", target)
        time.sleep(0.3)
        e = extra()
        r.check(0 <= e <= 24, f'{target} target: no blank scroll below the content', f'{e}px below the page content')
    driver.execute_script("document.getElementById('cheatExpandBtn').click();")
    time.sleep(0.3)
    e = extra()
    r.check(0 <= e <= 24, 'cheat sheet expanded: no blank scroll below the content', f'{e}px')
    driver.execute_script("document.getElementById('cheatExpandBtn').click();"
                          "document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")


def test_step_keyboard_shortcuts(driver, r):
    """From a step's checkbox or buttons: Alt+Up / Alt+Down move the step
    (focus stays on it) and Delete removes it (focus moves to the next
    step). They do nothing in the step's dropdown or text boxes, where
    those keys already mean something, and Ctrl+Z undoes a keyboard
    delete. Driven with real key presses."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys

    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1', debounced=True)

    def chain():
        return driver.execute_script(
            "return [].map.call(document.querySelectorAll('#chain .step'), function(r){"
            "  return r.querySelector('.s-type').value + ':' + [].map.call(r.querySelectorAll('.p-arg'), function(a){ return a.value; }).join(''); });")

    def focused():
        return driver.execute_script(
            "var e = document.activeElement, r = e.closest && e.closest('.step');"
            "return {cls: String(e.className).split(' ')[0], step: r ? [].indexOf.call(document.querySelectorAll('#chain .step'), r) + 1 : null};")

    def boxes():
        return driver.find_elements('css selector', '#chain .s-enabled')

    def press(*keys):
        ActionChains(driver).key_down(keys[0]).send_keys(*keys[1:]).key_up(keys[0]).perform() if len(keys) > 1 else ActionChains(driver).send_keys(keys[0]).perform()
        time.sleep(0.25)

    original = chain()                                   # [c, sa4, se3, si1]
    boxes()[1].send_keys('')                             # focus step 2's checkbox
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[1].focus();")
    press(Keys.ALT, Keys.ARROW_DOWN)
    r.check(chain() == [original[0], original[2], original[1], original[3]], 'Alt+Down on a checkbox moves the step down', f'{chain()}')
    f = focused()
    r.check(f['cls'] == 's-enabled' and f['step'] == 3, 'focus stays on the moved step', f'{f}')

    press(Keys.ALT, Keys.ARROW_UP)
    press(Keys.ALT, Keys.ARROW_UP)
    r.check(chain() == [original[1], original[0], original[2], original[3]], 'Alt+Up twice moves it to the top', f'{chain()}')
    f = focused()
    r.check(f['step'] == 1, 'focus follows the step to the top', f'{f}')
    press(Keys.ALT, Keys.ARROW_UP)
    announced = driver.execute_script("return document.getElementById('liveStatus').textContent;")
    r.check(chain() == [original[1], original[0], original[2], original[3]] and 'first step' in announced,
            'Alt+Up on the first step does nothing and says so', f'{announced!r}')

    # the dropdown and text boxes keep their own key meanings
    before = chain()
    driver.execute_script("document.querySelectorAll('#chain .s-type')[1].focus();")
    press(Keys.ALT, Keys.ARROW_DOWN)
    press(Keys.DELETE)
    r.check(chain() == before, 'Alt+Down and Delete do nothing inside a step\'s dropdown', f'{chain()}')
    driver.execute_script("document.querySelectorAll('#chain .p-arg')[0].focus();")
    press(Keys.DELETE)
    r.check(len(chain()) == len(before), 'Delete inside an argument box edits the text, not the step', f'{len(chain())} steps')
    # that Delete really edited the box; start the rest from a fresh chain
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1', debounced=True)
    before = chain()

    # Delete removes the focused step and moves focus to the next one; Ctrl+Z brings it back
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[1].focus();")
    press(Keys.DELETE)
    r.check(chain() == [before[0], before[2], before[3]], 'Delete on a checkbox removes that step', f'{chain()}')
    f = focused()
    r.check(f['cls'] == 's-enabled' and f['step'] == 2, 'focus moves to the next step\'s checkbox', f'{f}')
    press(Keys.CONTROL, 'z')
    r.check(chain() == before, 'Ctrl+Z then restores it', f'{chain()}')

    # and the buttons work the same way
    driver.execute_script("document.querySelectorAll('#chain .step')[1].querySelector('.down').focus();")
    press(Keys.ALT, Keys.ARROW_DOWN)
    r.check(chain() == [before[0], before[2], before[1], before[3]], 'Alt+Down also works from the step\'s buttons', f'{chain()}')


def test_tooltip_information_is_also_visible(driver, r):
    """Information that used to live only in hover tooltips is also in
    visible text (or exposed to assistive tech): the copy-rule caveat when
    a step is disabled, the step shortcuts while a step is focused, what
    the batch 'trace' buttons do, the 'Operators only' description, and
    'Step N' for the trace's numbers."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys

    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3', debounced=True)
    note = lambda: driver.execute_script("return document.getElementById('portabilityNote').textContent;")
    r.check('left out of the copy' not in note(), 'no copy caveat while every step is enabled', repr(note()))
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[1].click();")
    r.check('1 disabled step is left out of the copy' in note(), 'disabling a step says it is left out of the copy', repr(note()))
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[2].click();")
    r.check('2 disabled steps are left out of the copy' in note(), 'the caveat counts several disabled steps', repr(note()))
    # re-enable everything (the chain re-renders after each click, so look the boxes up fresh each time)
    for _ in range(4):
        driver.execute_script("var off = [].filter.call(document.querySelectorAll('#chain .s-enabled'), function(c){ return !c.checked; })[0]; if (off) off.click();")
    r.check('left out' not in note(), 'the caveat goes away once every step is enabled again', repr(note()))

    driver.execute_script("document.activeElement.blur();")
    hint = lambda: driver.execute_script("return {keys: !document.getElementById('hintKeys').hidden, hover: !document.getElementById('hintHover').hidden};")
    r.check(hint() == {'keys': False, 'hover': True}, 'the section 03 hint starts as the hover tip', f'{hint()}')
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[0].focus();")
    r.check(hint() == {'keys': True, 'hover': False}, 'focusing a step shows its keyboard shortcuts instead', f'{hint()}')
    driver.execute_script("document.querySelectorAll('#chain .s-type')[0].focus();")
    r.check(hint() == {'keys': False, 'hover': True}, 'in the step dropdown (where they do not apply) the hover tip is back', f'{hint()}')
    driver.execute_script("document.activeElement.blur();")

    sub = driver.execute_script("return document.querySelector('#col2Card .sub').textContent;")
    r.check('trace' in sub and 'step by step' in sub, 'the batch section explains the trace buttons', repr(sub))
    desc = driver.execute_script(
        "var c = document.getElementById('cheatOpOnly'), d = document.getElementById(c.getAttribute('aria-describedby'));"
        "return d ? d.textContent : null;")
    r.check(desc and 'operator itself' in desc, "'Operators only' has a description for assistive tech", repr(desc))
    num = driver.execute_script("return document.querySelector('#trace .num').textContent.replace(/\\s+/g, ' ').trim();")
    r.check(num == 'Step 1', "trace numbers read as 'Step N'", repr(num))


def test_auto_theme_follows_the_system(driver, r):
    """Auto follows the system's light/dark setting live, goes dark when the
    system doesn't say, is remembered across reloads, and an explicit Dark
    or Light ignores the system. Runs last (changes media emulation)."""
    def system(value):
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': value}]})
        time.sleep(0.2)

    def theme():
        return driver.execute_script(
            "var r = document.documentElement; return {theme: r.dataset.theme || 'dark',"
            "  pressed: [].filter.call(document.querySelectorAll('#themeSwitch button'), function(b){ return b.getAttribute('aria-pressed') === 'true'; })"
            "           .map(function(b){ return b.dataset.themeSet; })};")

    def choose(mode):
        driver.execute_script("document.querySelector('#themeSwitch [data-theme-set=\"' + arguments[0] + '\"]').click();", mode)
        time.sleep(0.2)

    try:
        system('light')
        driver.get(INDEX_URL)
        time.sleep(0.6)
        r.check(theme() == {'theme': 'dark', 'pressed': ['dark']}, 'with no saved choice the default is dark, even on a light system', f'{theme()}')
        choose('auto')
        r.check(theme() == {'theme': 'light', 'pressed': ['auto']}, 'Auto on a light system: light, with Auto pressed', f'{theme()}')
        system('dark')
        r.check(theme() == {'theme': 'dark', 'pressed': ['auto']}, 'Auto follows the system to dark live, staying on Auto', f'{theme()}')
        system('light')
        r.check(theme()['theme'] == 'light', 'and back to light live', f'{theme()}')
        driver.get(INDEX_URL)
        time.sleep(0.6)
        r.check(theme() == {'theme': 'light', 'pressed': ['auto']}, 'Auto is remembered across a reload (light, system is light)', f'{theme()}')
        system('no-preference')
        r.check(theme()['theme'] == 'dark', 'Auto with no system preference falls back to dark', f'{theme()}')
        system('dark')
        choose('light')
        r.check(theme() == {'theme': 'light', 'pressed': ['light']}, 'an explicit Light ignores a dark system', f'{theme()}')
        system('light')
        choose('dark')
        system('dark'); system('light')
        r.check(theme() == {'theme': 'dark', 'pressed': ['dark']}, 'an explicit Dark ignores system changes', f'{theme()}')
    finally:
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-color-scheme', 'value': ''}]})
        driver.execute_script("localStorage.removeItem('theme');")
        driver.get(INDEX_URL)


def test_step_hover_links_to_its_trace_row(driver, r):
    """Hovering (or focusing) a step in section 03 also lights up that
    step's row in the section 04 trace, scrolling the trace box if the row
    is out of view; a step that did not run has no row; the link survives a
    re-render. The changed characters in the trace are underlined as well
    as colored, so the change doesn't depend on telling colors apart."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)

    def linked():
        return driver.execute_script("return [].map.call(document.querySelectorAll('#trace .trace-row.linked'), function(r){ return r.dataset.step; });")

    def hover(n):
        driver.execute_script("document.querySelectorAll('#chain .step')[arguments[0] - 1].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));", n)

    r.check(linked() == [], 'no trace row is linked until a step is hovered')
    hover(2)
    r.check(linked() == ['2'], 'hovering step 2 links trace row 2', f'{linked()}')
    hover(3)
    r.check(linked() == ['3'], 'moving to step 3 moves the link', f'{linked()}')
    driver.execute_script("document.getElementById('chain').dispatchEvent(new MouseEvent('mouseleave'));")
    r.check(linked() == [], 'leaving the list clears the link', f'{linked()}')

    # keyboard focus links it too
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[1].focus();")
    r.check(linked() == ['2'], 'focusing a step links its trace row as well', f'{linked()}')
    driver.execute_script("document.activeElement.blur();")

    # a row below the fold of the trace box gets scrolled into view
    driver.execute_script("document.getElementById('trace').scrollTop = 0;")
    hover(7)
    inview = driver.execute_script(
        "var t = document.getElementById('trace'), row = t.querySelector('.trace-row.linked'); if (!row) return null;"
        "var box = t.getBoundingClientRect(), b = row.getBoundingClientRect(), top = box.top, bot = box.bottom;"
        "if (t.classList.contains('locked')){"   # the pinned first/last rows cover part of the box
        "  if (row !== t.firstElementChild) top = Math.max(top, t.firstElementChild.getBoundingClientRect().bottom);"
        "  if (row !== t.lastElementChild) bot = Math.min(bot, t.lastElementChild.getBoundingClientRect().top); }"
        "return b.top >= top - 1 && b.bottom <= bot + 1;")
    r.check(inview is True, 'hovering a step whose trace row is out of view scrolls the trace to show it', f'in view: {inview}')

    # editing while hovered keeps the link (the trace re-renders)
    hover(2)
    driver.execute_script("var i = document.querySelectorAll('#chain .step')[1].querySelector('.p-arg'); i.value = 'q'; i.dispatchEvent(new Event('input', {bubbles: true}));")
    r.check(linked() == ['2'], 'the link survives a trace re-render', f'{linked()}')

    # a disabled step did not run, so there is no row to link
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[2].click();")
    hover(3)
    r.check(linked() == [], 'a disabled step has no trace row to link', f'{linked()}')

    # underline as well as color for what changed
    deco = driver.execute_script("var h = document.querySelector('#trace .word .hl'); return h ? getComputedStyle(h).textDecorationLine : null;")
    r.check(deco == 'underline', 'changed characters in the trace are underlined, not only colored', f'{deco!r}')


def test_trace_row_hover_links_back_to_its_step(driver, r):
    """The link works from the other side too: hovering a row in the
    section 04 trace lights up the step card in section 03 and that step's
    token in the rule line (scrolling the chain list if the card is out of
    view). The 'starting word' row belongs to no step, and a step hovered
    from the chain gets the same card highlight."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)

    def state():
        return driver.execute_script(
            "var card = document.querySelector('#chain .step.linked'), tok = document.querySelector('#ruleHl .hl-on');"
            "return {card: card ? [].indexOf.call(document.querySelectorAll('#chain .step'), card) + 1 : null,"
            "        token: tok ? tok.textContent : null,"
            "        row: (document.querySelector('#trace .trace-row.linked') || {dataset: {}}).dataset.step || null};")

    def hover_row(n):
        driver.execute_script("document.querySelector('#trace .trace-row[data-step=\"' + arguments[0] + '\"]').dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));", n)

    r.check(state() == {'card': None, 'token': None, 'row': None}, 'nothing is linked to start with', f'{state()}')
    hover_row(2)
    r.check(state() == {'card': 2, 'token': 'sa4', 'row': '2'}, 'hovering trace row 2 lights up step 2 and its token in the rule line', f'{state()}')
    hover_row(5)
    r.check(state() == {'card': 5, 'token': 'so0', 'row': '5'}, 'moving to trace row 5 moves the link to step 5 and its token', f'{state()}')
    driver.execute_script("document.getElementById('trace').dispatchEvent(new MouseEvent('mouseleave'));")
    r.check(state() == {'card': None, 'token': None, 'row': None}, 'leaving the trace clears every highlight', f'{state()}')

    driver.execute_script("document.querySelector('#trace .trace-row.start').dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));")
    r.check(state() == {'card': None, 'token': None, 'row': None}, 'the starting-word row belongs to no step, so it links nothing', f'{state()}')

    # a card hidden below the chain list's fold is scrolled into view
    driver.execute_script("document.getElementById('chain').scrollTop = 0; document.getElementById('trace').scrollTop = 9999;")
    hover_row(8)
    inview = driver.execute_script(
        "var c = document.getElementById('chain').getBoundingClientRect(), card = document.querySelector('#chain .step.linked');"
        "if (!card) return null; var b = card.getBoundingClientRect(); return b.top >= c.top - 1 && b.bottom <= c.bottom + 1;")
    r.check(inview is True, 'hovering a trace row whose step card is out of view scrolls the chain list to it', f'in view: {inview}')

    # the card highlight survives a chain re-render, and a chain-side hover shows it too
    driver.execute_script("var i = document.querySelectorAll('#chain .step')[7].querySelector('.p-arg'); i.value = '2'; i.dispatchEvent(new Event('input', {bubbles: true}));")
    driver.execute_script("document.getElementById('trace').dispatchEvent(new MouseEvent('mouseleave'));")
    driver.execute_script("document.querySelectorAll('#chain .step')[2].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));")
    r.check(state()['card'] == 3 and state()['row'] == '3', 'hovering a step card highlights the card itself as well as its row and token', f'{state()}')
    driver.execute_script("document.getElementById('chain').dispatchEvent(new MouseEvent('mouseleave'));")


def test_rule_line_hover_links_its_step(driver, r):
    """Hovering a token in the rule line (a real mouse) links its step: the
    card in section 03, the row in section 04 and the token itself. Gaps
    between tokens and the area past the text link nothing, it also works
    when a long line has scrolled sideways, and the linked trace row is
    brought into the visible part of the list (not under a pinned row)."""
    from selenium.webdriver.common.action_chains import ActionChains
    import re

    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    rule = 'c sa4 se3 si1 so0 ss5 $! $1'
    box = driver.find_element('id', 'ruleTextInput')
    set_value(driver, box, rule, debounced=True)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", box)
    time.sleep(0.2)

    metrics = driver.execute_script(
        "var i = document.getElementById('ruleTextInput'), cs = getComputedStyle(i), c = document.createElement('canvas').getContext('2d');"
        "c.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;"
        "return {cw: c.measureText('0').width, left: parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft)};")

    def over(char_pos):
        """move the real mouse to the middle of the character at char_pos"""
        w = box.rect['width']
        x = metrics['left'] + (char_pos + 0.5) * metrics['cw'] - box.scroll_offset if False else metrics['left'] + (char_pos + 0.5) * metrics['cw']
        ActionChains(driver).move_to_element_with_offset(box, int(x - w / 2), 0).perform()
        time.sleep(0.15)

    def linked():
        return driver.execute_script(
            "var t = document.querySelector('#ruleHl .hl-on'), c = document.querySelector('#chain .step.linked'), w = document.querySelector('#trace .trace-row.linked');"
            "return [t && t.textContent, c && [].indexOf.call(document.querySelectorAll('#chain .step'), c) + 1, w && w.dataset.step];")

    tokens = [(m.group(), m.start()) for m in re.finditer(r'\S+', rule)]
    for n, (tok, start) in enumerate(tokens, 1):
        over(start + len(tok) // 2)
        r.check(linked() == [tok, n, str(n)], f'hovering "{tok}" in the rule line links step {n}, its card and its trace row', f'{linked()}')
    over(1)   # the space after 'c'
    r.check(linked() == [None, None, None], 'hovering the gap between two tokens links nothing', f'{linked()}')
    over(len(rule) + 4)
    r.check(linked() == [None, None, None], 'hovering past the end of the text links nothing', f'{linked()}')

    # the linked trace row is really visible (not behind the pinned start/end rows)
    driver.execute_script("document.getElementById('trace').scrollTop = 0;")
    over(2)
    vis = driver.execute_script(
        "var t = document.getElementById('trace'), row = t.querySelector('.trace-row.linked'); if (!row) return null;"
        "var b0 = t.getBoundingClientRect(), b = row.getBoundingClientRect(), top = b0.top, bot = b0.bottom;"
        "if (t.classList.contains('locked')){"
        "  if (row !== t.firstElementChild) top = Math.max(top, t.firstElementChild.getBoundingClientRect().bottom);"
        "  if (row !== t.lastElementChild) bot = Math.min(bot, t.lastElementChild.getBoundingClientRect().top); }"
        "return b.top >= top - 1 && b.bottom <= bot + 1;")
    r.check(vis is True, 'the linked trace row is brought fully into view, not hidden under a pinned row', f'visible: {vis}')

    # a long line that scrolls sideways still maps correctly
    long_rule = ' '.join(['c', 'sa4', 'se3', 'si1', 'so0', 'ss5', '$!', '$1'] * 4)
    set_value(driver, box, long_rule, debounced=True)
    driver.execute_script("var i = document.getElementById('ruleTextInput'); i.scrollLeft = i.scrollWidth;")
    time.sleep(0.2)
    sl = driver.execute_script("return document.getElementById('ruleTextInput').scrollLeft;")
    last_start = len(long_rule) - 2           # the final '$1'
    w = box.rect['width']
    x = metrics['left'] + (last_start + 1) * metrics['cw'] - sl
    ActionChains(driver).move_to_element_with_offset(box, int(x - w / 2), 0).perform()
    time.sleep(0.2)
    got = linked()
    r.check(sl > 0 and got[0] == '$1' and got[1] is not None, 'with the line scrolled sideways, the token under the mouse is still the one linked', f'scrollLeft {sl}, {got}')
    ActionChains(driver).move_to_element(driver.find_element('id', 'wordInput')).perform()
    set_value(driver, box, rule, debounced=True)


def test_rule_line_caret_links_its_step(driver, r):
    """With nothing hovered, the text cursor in the rule line links the
    step whose token it is in (or at the end of, or at the start of): the
    token, its card and its trace row light up. A selection across several
    tokens links nothing; typing a new token links its new step once the
    chain rebuilds; leaving the box clears it. Real keyboard input."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys

    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    box = driver.find_element('id', 'ruleTextInput')
    set_value(driver, box, 'c sa4 se3', debounced=True)

    def linked():
        return driver.execute_script(
            "var t = document.querySelector('#ruleHl .hl-on'), c = document.querySelector('#chain .step.linked'), w = document.querySelector('#trace .trace-row.linked');"
            "return [t && t.textContent, c && [].indexOf.call(document.querySelectorAll('#chain .step'), c) + 1, w && w.dataset.step];")

    def keys(*k):
        ActionChains(driver).send_keys(*k).perform()
        time.sleep(0.15)

    ActionChains(driver).move_to_element(driver.find_element('id', 'wordInput')).perform()   # mouse well away from the rule line
    box.click()
    keys(Keys.HOME)                                       # caret before 'c'
    r.check(linked() == ['c', 1, '1'], 'caret at the start of "c" links step 1', f'{linked()}')
    keys(Keys.ARROW_RIGHT)                                # after 'c'
    r.check(linked() == ['c', 1, '1'], 'caret at the end of "c" still links step 1', f'{linked()}')
    keys(Keys.ARROW_RIGHT)                                # before 'sa4' (past the space)
    r.check(linked() == ['sa4', 2, '2'], 'caret at the start of "sa4" links step 2', f'{linked()}')
    keys(Keys.ARROW_RIGHT)                                # between s and a
    r.check(linked() == ['sa4', 2, '2'], 'caret inside "sa4" links step 2', f'{linked()}')
    keys(Keys.ARROW_RIGHT, Keys.ARROW_RIGHT)              # after 'sa4'
    r.check(linked() == ['sa4', 2, '2'], 'caret at the end of "sa4" links step 2', f'{linked()}')
    keys(Keys.ARROW_RIGHT, Keys.ARROW_RIGHT)              # inside 'se3'
    r.check(linked()[0] == 'se3' and linked()[1] == 3, 'moving on, the link follows to "se3" / step 3', f'{linked()}')

    def shift_right(n):
        # hold Shift only for these presses (Selenium otherwise leaves it down)
        chain = ActionChains(driver).key_down(Keys.SHIFT)
        for _ in range(n):
            chain = chain.send_keys(Keys.ARROW_RIGHT)
        chain.key_up(Keys.SHIFT).perform()
        time.sleep(0.15)

    keys(Keys.HOME)
    shift_right(4)                                        # selects 'c sa'
    sel = driver.execute_script("var i = document.getElementById('ruleTextInput'); return [i.selectionStart, i.selectionEnd];")
    r.check(linked() == [None, None, None], 'a selection across several tokens links nothing', f'selection {sel}, {linked()}')
    keys(Keys.HOME)
    keys(Keys.ARROW_RIGHT, Keys.ARROW_RIGHT)
    shift_right(2)                                        # selects 'sa' inside sa4
    r.check(linked() == ['sa4', 2, '2'], 'a selection inside one token links that token', f'{linked()}')

    # typing a new token: after the chain rebuilds, its step is linked
    keys(Keys.END)
    keys(' ss5')
    time.sleep(0.7)
    steps_now = driver.execute_script("return document.querySelectorAll('#chain .step').length;")
    r.check(steps_now == 4 and linked() == ['ss5', 4, '4'], 'typing a new token links its new step once the chain rebuilds', f'{steps_now} steps, {linked()}')

    # the mouse takes over while hovering a token, and the caret takes back over afterwards
    ActionChains(driver).move_to_element(driver.find_element('id', 'wordInput')).perform()
    time.sleep(0.15)
    r.check(linked()[0] == 'ss5', 'with the mouse elsewhere, the caret link is back', f'{linked()}')

    box.send_keys(Keys.TAB)                                # leave the box
    time.sleep(0.15)
    r.check(linked() == [None, None, None], 'leaving the rule line clears the caret link', f'{linked()}')
    set_value(driver, box, 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)


def test_batch_rows_keep_their_line_numbers(driver, r):
    """Each batch table row shows the line number it came from in the
    input box; a blank line is skipped but leaves a gap in the numbers,
    so a row can always be matched to its line."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'batchInput'), 'alpha\n\nbravo\n   \ncharlie\ndelta')
    rows = driver.execute_script(
        "return [].map.call(document.querySelectorAll('#batchBody tr'), function(tr){"
        "  return [tr.querySelector('td.b-n').textContent, tr.querySelector('td.b-in').textContent]; });")
    r.check(rows == [['1', 'alpha'], ['3', 'bravo'], ['5', 'charlie'], ['6', 'delta']],
            'rows keep their input-line numbers, with gaps where lines were blank', f'{rows}')
    head = driver.execute_script("return document.querySelector('table.batch th.b-n').textContent;")
    r.check(head == '#', 'the number column has a header', repr(head))
    set_value(driver, driver.find_element('id', 'batchInput'), 'password\ndragon\nsunshine\nletmein\nprincess')


def test_batch_wrap_toggle(driver, r):
    """'Wrap long lines' is one toggle for the batch box and table. On (the
    default): long entries wrap, nothing scrolls sideways. Off: every entry
    stays on one line, the box and the table scroll sideways, and the
    'trace' buttons stay pinned in view."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    long1 = 'correcthorsebatterystaple' * 3
    long2 = 'Winter2023!WinterIsComing-ThisIsAVeryLongPassphrase1234567890'
    set_value(driver, driver.find_element('id', 'batchInput'), f'password\n{long1}\nsunshine\n{long2}')

    def info():
        return driver.execute_script(
            "var t = document.getElementById('batchInput'), w = document.querySelector('.batch-scroll'), rows = document.querySelectorAll('#batchBody tr');"
            "var btn = rows[1].querySelector('.tracebtn').getBoundingClientRect(), box = w.getBoundingClientRect();"
            "return {checked: document.getElementById('batchWrap').checked, wrapAttr: t.getAttribute('wrap'),"
            "  taOverflow: t.scrollWidth > t.clientWidth + 1, tableOverflow: w.scrollWidth > w.clientWidth + 1,"
            "  heights: [].map.call(rows, function(x){ return Math.round(x.getBoundingClientRect().height); }),"
            "  btnVisible: btn.right <= box.right + 1 && btn.left >= box.left - 1};")

    on = info()
    r.check(on['checked'] and on['wrapAttr'] == 'soft', 'wrapping is on by default', f'{on}')
    r.check(not on['taOverflow'] and not on['tableOverflow'], 'wrap on: nothing scrolls sideways', f'{on}')
    r.check(max(on['heights']) > 60, 'wrap on: long entries wrap onto several lines (tall rows)', f"{on['heights']}")

    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    off = info()
    r.check(not off['checked'] and off['wrapAttr'] == 'off', 'unchecking turns wrapping off for the box', f'{off}')
    r.check(off['taOverflow'], 'wrap off: the box scrolls sideways for long entries', f'{off}')
    r.check(off['tableOverflow'], 'wrap off: the table scrolls sideways too', f'{off}')
    r.check(max(off['heights']) < 50, 'wrap off: every row stays on one line', f"{off['heights']}")
    r.check(off['btnVisible'], 'wrap off: the trace button stays pinned in view', f'{off}')

    cols = driver.execute_script("return ['col1Card', 'col2Card', 'cheatCard'].map(function(id){ return Math.round(document.getElementById(id).getBoundingClientRect().height); });")
    r.check(len(set(cols)) == 1, 'wrap off: the three columns are still equal height', f'{cols}')

    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    back = info()
    r.check(back['checked'] and back['wrapAttr'] == 'soft' and not back['tableOverflow'], 'turning it back on restores wrapping', f'{back}')
    set_value(driver, driver.find_element('id', 'batchInput'), 'password\ndragon\nsunshine\nletmein\nprincess')


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
        test_document_basics(driver, r)
        test_every_control_has_an_accessible_name(driver, r)
        test_toggle_groups_expose_pressed_state(driver, r)
        test_live_announcements(driver, r)
        test_click_targets_are_big_enough(driver, r)
        test_delete_can_be_undone(driver, r)
        test_step_keyboard_shortcuts(driver, r)
        test_tooltip_information_is_also_visible(driver, r)
        test_step_hover_links_to_its_trace_row(driver, r)
        test_trace_row_hover_links_back_to_its_step(driver, r)
        test_rule_line_hover_links_its_step(driver, r)
        test_rule_line_caret_links_its_step(driver, r)
        test_batch_rows_keep_their_line_numbers(driver, r)
        test_batch_wrap_toggle(driver, r)
        test_compat_operators_have_a_non_color_marker(driver, r)
        test_page_has_no_phantom_scroll(driver, r)
        test_columns_stay_equal_height(driver, r)
        test_tall_window_shrinks_chain_instead_of_padding_trace(driver, r)
        test_columns_refit_on_window_resize(driver, r)
        test_reduced_motion_is_respected(driver, r)
        test_auto_theme_follows_the_system(driver, r)
        test_validator_inline_edit_live_reparse(driver, r)
        test_validator_restore(driver, r)
        test_validator_dialect_switch_reparses_and_preserves_deletions(driver, r)
    finally:
        driver.quit()

    return r.summarize()


if __name__ == '__main__':
    sys.exit(main())
