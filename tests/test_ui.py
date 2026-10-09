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
    - the three target views agree (Hashcat = all but John-only, Both =
      minus hashcat-only, John = shared + John-only) and 'vNX' is hashcat-only
    - the Both callout is a code block plus short points
    - cheat sheet search keeps the John-only box's explanation, and a
      search with no results just says so
    - the help dialog opens from the Help button or ? (not while typing),
      traps Tab, closes on Esc / Close / backdrop, returns focus, and
      documents the shortcuts that exist
    - the Link highlights / Scroll to match switches (off stops all
      linking, scrolling can be stopped on its own, both remembered, and
      both default to off under reduce-motion unless chosen)
    - both themes meet WCAG AA: text 4.5:1 (3:1 large) in the rare-color
      states, and every control edge 3:1
    - High contrast meets WCAG AAA (text 7:1, control edges 4.5:1) in both
      themes, and its switch works, is remembered and follows the system's
      'more contrast' setting unless a choice was made
    - in forced-colors mode (Windows High Contrast) the active toggle, the
      linked-step highlights and the drag handle are still visible
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
        "var rows = document.querySelectorAll('#trace .trace-row:not(.skipped)');"   # skipped rows are dimmed placeholders
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
    # No per-word divergence check failed here, so the note is just the single "Portable" line —
    # class 'sub' (not 'sub ok') since that color now lives on an inner span, not the element itself,
    # so a later divergence on some other word can color just the warning without recoloring this line.
    r.check(n3['cls'] == 'sub' and n3['text'].startswith('✓ Portable'),
            '"Both" target with an all-shared chain: portability note confirms it\'s portable', n3)

    driver.find_element('css selector', '#targetBtns .tbtn[data-target="john_native"]').click()
    n4 = note()
    r.check(n4['cls'] == 'sub ok' and n4['text'].startswith('✓ Portable — also valid as plain hashcat syntax'),
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
        # The columns are now sized to leave room for the target-syntax row right above the grid
        # too, not just to fit the raw window height — so these heights sit in the range where
        # that leftover room (not a column's own minimum-content floor, and not the natural
        # content height either) is what's actually driving the size; a shorter window falls back
        # to the floor and holds steady instead of shrinking further, which would make a false
        # negative out of this test.
        size(1500, 1000)
        driver.get(INDEX_URL)
        time.sleep(0.8)
        a = cols()
        r.check(a['c1'] == a['c2'] == a['c3'] and a['c1'] <= a['vh'], 'sanity: equal columns that fit at 1500x1000', f'{a}')

        size(1500, 1150)
        b = cols()
        r.check(b['c1'] == b['c2'] == b['c3'] and b['c1'] > a['c1'],
                'making the window taller re-fits the columns (equal, and taller than before)', f'{a["c1"]}px -> {b["c1"]}px')

        size(1500, 950)
        c = cols()
        r.check(c['c1'] == c['c2'] == c['c3'] and c['c1'] < b['c1'],
                'making the window shorter re-fits the columns again (equal, and shorter)', f'{b["c1"]}px -> {c["c1"]}px')

        size(1000, 900)
        n = cols()
        r.check(n['chain'] <= 560 and n['trace'] <= 420,
                'in the stacked narrow layout the lists use their stylesheet caps, not the column fit', f'{n}')

        size(1500, 1000)
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
    r.check(live() == 'Step moved down to position 3 of 9', 'moving a step down announces its new position', repr(live()))

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
    set_value(driver, driver.find_element('id', 'cheatSearch'), 'reverse')
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
    spoken prefix, and shared operators carry neither — except for the
    independent CPU-only marker (needs hashcat's -j/-k engine, not the -r
    GPU kernel), which can land on a shared, hashcat-only, or (in the Both
    tab) a shared-but-CPU-only row alike, and never appears in the
    John-native tab since the CPU/GPU split is a hashcat engine detail."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    js = ("var rows = [].slice.call(document.querySelectorAll('#cheatBody > .cheat-row'));"
          "var count = function(cls){ var colored = rows.filter(function(x){ return x.querySelector('.syntax.' + cls); });"
          "  return {colored: colored.length,"
          "    tagged: colored.filter(function(x){ return x.querySelector('.desc .mk.' + cls); }).length,"
          "    spoken: colored.filter(function(x){ return /only: /.test((x.querySelector('.desc .sr-only') || {}).textContent || ''); }).length}; };"
          "return {hc: count('tok-hc'), john: count('tok-john'),"
          "        cpuMarks: document.querySelectorAll('#cheatBody .desc .mk.tok-cpu').length,"
          "        marks: document.querySelectorAll('#cheatBody .desc .mk').length};")
    for target, key, label in (('hashcat', 'hc', 'HC'), ('john_native', 'john', 'J')):
        driver.execute_script("document.querySelector('#targetBtns [data-target=\"' + arguments[0] + '\"]').click();", target)
        m = driver.execute_script(js)
        c = m[key]
        r.check(c['colored'] > 0 and c['colored'] == c['tagged'] == c['spoken'] and m['marks'] == c['colored'] + m['cpuMarks'],
                f"{target} tab: every {label}-only operator has the {label} tag and a spoken prefix, and only CPU-only rows get anything extra", f'{m}')
    r.check(driver.execute_script("return document.querySelectorAll('#cheatBody .desc .mk.tok-cpu').length;") == 0,
            'the John-native tab has no CPU-only marks (the CPU/GPU split doesn’t apply to John)')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"both\"]').click();")
    m = driver.execute_script(js)
    r.check(m['hc']['colored'] == 0 and m['john']['colored'] == 0 and m['marks'] == m['cpuMarks'] and m['cpuMarks'] > 0,
            'Both tab: no operator is HC/John-tagged (only shared ones are listed), but some are still CPU-only-marked', f'{m}')
    legend = driver.execute_script("return [].map.call(document.querySelectorAll('.compat-key .mk'), function(x){ return x.textContent; });")
    r.check(legend == ['HC', 'J', 'CPU'], 'the legend shows the HC, J and CPU tags', f'{legend}')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")


def test_native_compat_dialog_opens_and_closes(driver, r):
    """The John-native cheat sheet count line links to a reference dialog (built into this same
    file, not a separate page — the app stays a single self-contained HTML file) breaking down
    which of the 56 shared operators actually behave identically with no hashcat-compat wrapper.
    It only appears in the John-native view, opens on click, and closes on its own close button."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    r.check(driver.execute_script("return document.getElementById('compatOpenBtn');") is None,
            'the compatibility link does not appear outside the John-native view')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"john_native\"]').click();")
    btn = driver.find_element('id', 'compatOpenBtn')
    btn.click()
    info = driver.execute_script("""
      var dlg = document.getElementById('compatDialog');
      return {open: dlg.open, stats: dlg.querySelectorAll('.compatstat').length,
              causes: dlg.querySelectorAll('.compatcause').length,
              ops: dlg.querySelectorAll('.compatops .op').length};
    """)
    r.check(info['open'] and info['stats'] == 4 and info['causes'] == 5 and info['ops'] == 56,
            'the dialog opens with all 56 operators accounted for across its groups', f'{info}')
    driver.find_element('id', 'compatClose').click()
    r.check(not driver.execute_script("return document.getElementById('compatDialog').open;"),
            'the close button closes it')
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
    r.check('trace button' in sub and 'how that word changes' in sub, 'the batch section explains the trace buttons in plain words', repr(sub))
    r.check('\u2191' not in sub, 'the explanation does not quote the arrow glyph', repr(sub))
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
        "  var end = t.querySelector('.trace-row.outcome') || t.lastElementChild, er = end.getBoundingClientRect();"
        "  if (row !== end && er.bottom >= box.bottom - 1) bot = Math.min(bot, er.top); }"
        "return b.top >= top - 1 && b.bottom <= bot + 1;")
    r.check(inview is True, 'hovering a step whose trace row is out of view scrolls the trace to show it', f'in view: {inview}')

    # editing while hovered keeps the link (the trace re-renders)
    hover(2)
    driver.execute_script("var i = document.querySelectorAll('#chain .step')[1].querySelector('.p-arg'); i.value = 'q'; i.dispatchEvent(new Event('input', {bubbles: true}));")
    r.check(linked() == ['2'], 'the link survives a trace re-render', f'{linked()}')

    # a disabled step did not run: it keeps a dimmed placeholder row, and that row still links
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[2].click();")
    hover(3)
    r.check(linked() == ['3'] and driver.execute_script("return document.querySelector('#trace .trace-row.linked').classList.contains('skipped');"),
            'a disabled step keeps a dimmed trace row, and it still links', f'{linked()}')

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


def test_final_trace_row_still_highlights_when_pinned(driver, r):
    """With 'Lock start/end rows' on (the default), the last trace row is sticky-pinned and sets
    its own background/box-shadow for the drop shadow — one more class than .trace-row.linked, so
    without the fix a hovered last step's row loses the highlight to that higher-specificity rule."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    last_step = driver.find_elements('css selector', '#chain .step')[-1]
    driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));", last_step)
    info = driver.execute_script(
        "var row = document.querySelector('#trace .trace-row.linked'); if (!row) return null;"
        "var linkedBg = getComputedStyle(row).backgroundColor, hasInset = getComputedStyle(row).boxShadow.indexOf('inset') >= 0;"
        "row.classList.remove('linked');"   # measure the SAME row's own un-tinted pinned background, theme-independently
        "var plainBg = getComputedStyle(row).backgroundColor;"
        "row.classList.add('linked');"
        "return {locked: document.getElementById('trace').classList.contains('locked'), linkedBg: linkedBg, plainBg: plainBg, hasInset: hasInset};")
    r.check(info and info['locked'] and info['linkedBg'] != info['plainBg'] and info['hasInset'],
            "the last (pinned) trace row keeps its accent tint and inset border when linked", f'{info}')
    driver.execute_script("document.getElementById('chain').dispatchEvent(new MouseEvent('mouseleave'));")


def test_scroll_to_show_clears_row_near_the_end_when_locked(driver, r):
    """With 'Lock start/end rows' on, scrollToShow used to decide whether the pinned end
    row is "currently stuck" by comparing its live bounding rect to the box's bottom edge
    within 1px — a check that depends on the current scroll position and, in Firefox at
    some viewport sizes, missed by a fraction of a pixel (sub-pixel layout rounding this
    project's Chromium-based test harness doesn't reproduce), silently skipping the
    narrowing and leaving a row stuck half-covered with no further scroll attempted.
    Narrowing by the pinned rows' own height instead removes the dependency on current
    scroll position entirely: this pins down that a row needing to clear the pinned
    outcome row ends up fully clear regardless of where scrolling started from."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1 $2 $3', debounced=True)
    steps = driver.find_elements('css selector', '#chain .step')
    r.check(len(steps) >= 8, 'the chain has enough steps for a row near the end', f'{len(steps)}')
    target_idx = len(steps) - 2  # second-to-last: a row that must clear the pinned outcome row, but is not it

    def clear_from(start_scroll_top):
        return driver.execute_script(
            "var t = document.getElementById('trace');"
            "t.scrollTop = arguments[0];"
            "var row = t.querySelectorAll('.trace-row:not(.outcome)')[arguments[1]];"
            "window.__test.scrollToShow(t, row);"
            "var first = t.firstElementChild, end = t.querySelector('.trace-row.outcome') || t.lastElementChild;"
            "var tb = t.getBoundingClientRect(), rb = row.getBoundingClientRect();"
            "var topLimit = tb.top + first.getBoundingClientRect().height;"
            "var botLimit = tb.bottom - end.getBoundingClientRect().height;"
            "return {scrollable: t.scrollHeight > t.clientHeight + 1, scrollTop: t.scrollTop,"
            "        fullyClear: rb.top >= topLimit - 0.5 && rb.bottom <= botLimit + 0.5};",
            start_scroll_top, target_idx)

    max_scroll = driver.execute_script("var t = document.getElementById('trace'); return t.scrollHeight;")
    from_top = clear_from(0)
    from_bottom = clear_from(max_scroll)
    r.check(from_top and from_top['scrollable'], 'the locked trace is actually scrollable in this scenario', f'{from_top}')
    r.check(from_top and from_top['fullyClear'], 'starting scrolled to the top, the target row ends up fully clear', f'{from_top}')
    r.check(from_bottom and from_bottom['fullyClear'], 'starting scrolled to the bottom, the same target row still ends up fully clear', f'{from_bottom}')


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
        "  var end = t.querySelector('.trace-row.outcome') || t.lastElementChild, er = end.getBoundingClientRect();"
        "  if (row !== end && er.bottom >= b0.bottom - 1) bot = Math.min(bot, er.top); }"
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


def test_batch_box_line_number_gutter(driver, r):
    """The batch box has a line-number gutter in both wrap modes: one cell
    per line, each as tall as that entry really is (a wrapped entry spans
    several visual lines), so the cells add up to the box's real scroll
    height; it scrolls with the text, and widens for 100+ lines."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    long1 = 'correcthorsebatterystaple' * 3
    set_value(driver, driver.find_element('id', 'batchInput'), f'password\n\n{long1}\nsunshine\nletmein\nprincess\nalpha')   # overflows the 5-line box

    def gutter():
        return driver.execute_script(
            "var t = document.getElementById('batchInput'), cs = getComputedStyle(t), lh = parseFloat(cs.lineHeight),"
            "    cells = [].slice.call(document.querySelectorAll('#batchGutterInner > div'));"
            "var sum = cells.reduce(function(a, c){ return a + c.getBoundingClientRect().height; }, 0);"
            "return {nums: cells.map(function(c){ return c.textContent; }),"
            "        lines: cells.map(function(c){ return Math.round(c.getBoundingClientRect().height / lh); }),"
            "        diff: (function(){ var content = sum + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);"
            "           /* scrollHeight is the content's height only when the content overflows the box */"
            "           return content > t.clientHeight + 1 ? Math.abs(content - t.scrollHeight) : (content <= t.scrollHeight + 1 ? 0 : content - t.scrollHeight); })(),"
            "        width: parseFloat(getComputedStyle(document.getElementById('batchGutter')).width),"
            "        padLeft: parseFloat(cs.paddingLeft)};")

    g = gutter()
    r.check(g['nums'] == ['1', '2', '3', '4', '5', '6', '7'], 'one number per line of the box, blank lines included', f"{g['nums']}")
    r.check(g['lines'][2] >= 2 and g['lines'][0] == 1, 'wrap on: a long entry gets a cell as tall as its wrapped lines', f"{g['lines']}")
    r.check(g['diff'] <= 1.5, 'wrap on: the cells add up to the box\'s real scroll height (they match the real wrapping)', f"off by {g['diff']}px")

    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    g = gutter()
    r.check(g['lines'] == [1, 1, 1, 1, 1, 1, 1], 'wrap off: every number gets exactly one line', f"{g['lines']}")
    r.check(g['diff'] <= 1.5, 'wrap off: the cells still add up to the real scroll height', f"off by {g['diff']}px")
    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)

    many = '\n'.join('word%d' % i for i in range(1, 31))
    set_value(driver, driver.find_element('id', 'batchInput'), many)
    driver.execute_script("document.getElementById('batchInput').scrollTop = 40;")
    time.sleep(0.2)
    tr = driver.execute_script("return document.getElementById('batchGutterInner').style.transform;")
    r.check(tr == 'translateY(-40px)', 'the gutter scrolls with the text', f'{tr!r}')

    narrow = gutter()
    set_value(driver, driver.find_element('id', 'batchInput'), '\n'.join('w%d' % i for i in range(1, 130)))
    wide = gutter()
    r.check(wide['width'] > narrow['width'] and wide['padLeft'] > narrow['padLeft'], 'the gutter (and the box\'s left padding) widen once there are 100+ lines', f"{narrow['width']} -> {wide['width']}")
    set_value(driver, driver.find_element('id', 'batchInput'), 'password\ndragon\nsunshine\nletmein\nprincess')


def test_lists_keep_their_scroll_position(driver, r):
    """Re-fitting the columns used to throw a scrolled step list (and the
    trace) back to the top, because measuring briefly lifts each list's
    height cap. Toggling the batch wrap and editing an argument both
    re-fit, and neither may move a list the user has scrolled."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1 $2 $3 $4 $5', debounced=True)

    def pos():
        return driver.execute_script("return [Math.round(document.getElementById('chain').scrollTop), Math.round(document.getElementById('trace').scrollTop)];")

    driver.execute_script("document.getElementById('chain').scrollTop = 150; document.getElementById('trace').scrollTop = 70;")
    time.sleep(0.15)
    before = pos()
    r.check(before[0] > 0 and before[1] > 0, 'sanity: both lists are scrolled', f'{before}')
    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    r.check(pos() == before, 'toggling "Wrap long lines" does not move either list', f'{before} -> {pos()}')
    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    driver.execute_script("var i = document.querySelectorAll('#chain .step')[3].querySelector('.p-arg'); if (i){ i.value = '7'; i.dispatchEvent(new Event('input', {bubbles: true})); }")
    time.sleep(0.3)
    r.check(pos() == before, 'editing an argument in a scrolled list does not move either list', f'{before} -> {pos()}')
    driver.execute_script("document.getElementById('chain').scrollTop = 0; document.getElementById('trace').scrollTop = 0;")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)


def test_target_views_are_consistent(driver, r):
    """The three target views agree with each other and with the data:
    Hashcat shows every non-John-only operator, Both drops the
    hashcat-only ones, John (native) swaps them for the John-only ones;
    'vNX' (insert every N) is hashcat-only because John always reads v as
    assign-a-variable; the Both note's count matches its list."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def view(target):
        driver.execute_script("document.querySelector('#targetBtns [data-target=\"' + arguments[0] + '\"]').click();", target)
        time.sleep(0.3)
        return driver.execute_script(
            "var rows = [].slice.call(document.querySelectorAll('#cheatBody > .cheat-row'));"
            "return {rows: rows.length,"
            "  hc: rows.filter(function(x){ return x.querySelector('.mk.tok-hc'); }).length,"
            "  john: rows.filter(function(x){ return x.querySelector('.mk.tok-john'); }).length,"
            "  v: rows.filter(function(x){ return x.querySelector('.syntax').textContent === 'vNX'; }).length,"
            "  vHC: rows.filter(function(x){ return x.querySelector('.syntax').textContent === 'vNX' && x.querySelector('.mk.tok-hc'); }).length,"
            "  note: document.getElementById('targetNote').textContent};")

    counts = driver.execute_script(
        "var T = window.__test, keys = Object.keys(T.OPS);"
        "return {total: keys.length, johnOnly: keys.filter(function(k){ return T.OPS[k].johnOnly; }).length,"
        "        unsupported: keys.filter(function(k){ return T.JOHN_UNSUPPORTED[k]; }).length,"
        "        vUnsupported: !!T.JOHN_UNSUPPORTED.insert_every};")
    hc, both, jn = view('hashcat'), view('both'), view('john_native')
    r.check(counts['vUnsupported'], "'vNX' (insert_every) is classified hashcat-only")
    r.check(hc['rows'] == counts['total'] - counts['johnOnly'], 'Hashcat view lists every operator except the John-only ones', f"{hc['rows']} vs {counts}")
    r.check(both['rows'] == hc['rows'] - counts['unsupported'], 'Both view = the Hashcat list minus the hashcat-only operators', f"{both['rows']} vs {hc['rows']} - {counts['unsupported']}")
    r.check(jn['rows'] == both['rows'] + counts['johnOnly'], 'John view = the shared operators plus the John-only ones', f"{jn['rows']} vs {both['rows']} + {counts['johnOnly']}")
    r.check(hc['hc'] == counts['unsupported'] and both['hc'] == 0 and jn['hc'] == 0, 'every hashcat-only operator is tagged HC in the Hashcat view (and nowhere else)', f'{hc} {both} {jn}')
    r.check(hc['v'] == 1 and hc['vHC'] == 1 and both['v'] == 0 and jn['v'] == 0, "'vNX' appears, tagged HC, only in the Hashcat view", f"{hc['v']}/{hc['vHC']} {both['v']} {jn['v']}")
    r.check(f"the {both['rows']} operators" in both['note'], "the Both note's operator count matches what the view lists", f"{both['note'][:80]!r}")

    # John's own parser does not read v as insert-every
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"john_native\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c v4-', debounced=True)
    types = driver.execute_script("return [].map.call(document.querySelectorAll('#chain .s-type'), function(x){ return x.value; });")
    r.check('insert_every' not in types and driver.execute_script("return document.getElementById('ruleParseStatus').className.indexOf('err') >= 0;"),
            'in the John (native) view, "v4-" is not loaded as insert-every-N (the v is reported as skipped)', f'{types}')
    # in hashcat it still loads, with a warning that it will not run in John
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c v4-', debounced=True)
    note = driver.execute_script("return document.getElementById('portabilityNote').textContent;")
    r.check('Won’t run in John' in note and 'vNX' in note, 'in the Hashcat view, a rule using v loads and warns that it won\'t run in John', repr(note))


def test_both_view_warns_when_john_would_differ(driver, r):
    """"Portable" in the Both view means every step has a hashcat form John accepts, not that John
    gives the same result for this word — a handful of shared operators do differ (here: John's
    final max-length check, which hashcat's kernel engine doesn't have). The tool checks the actual
    word through both engines and warns when they disagree, rather than just asserting portability."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"both\"]').click();")
    note = lambda: driver.execute_script("return document.getElementById('portabilityNote').textContent;")
    set_value(driver, driver.find_element('id', 'wordInput'), 'abcdefghijklmnopqrstuvwxyz', debounced=True)
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'd d', debounced=True)   # 26 * 4 = 104 bytes
    n = note()
    r.check('Portable' in n and 'differs in John' in n and 'rejected' in n,
            'the Both view warns when a portable rule still gives a different result in John', repr(n))
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)
    n2 = note()
    r.check('Portable' in n2 and 'differs in John' not in n2, 'an ordinary rule gets no such warning', repr(n2))
    set_value(driver, driver.find_element('id', 'wordInput'), 'password', debounced=True)


def test_both_view_explains_the_hex_escape_syntax_error(driver, r):
    """A rule using hashcat's \\xNN byte-escape (like the default rule's final step) is valid
    hashcat syntax AND valid John-native syntax, but a genuine syntax error specifically inside
    John's hashcat-compat mode (verified against the real john binary: native mode decodes \\xNN
    normally, "!! hashcat logic ON" skips that preprocessor and chokes on the literal backslash).
    That's not a contradiction between the Both view's warning and the John-native view's
    "Portable" claim — they're different modes with genuinely different behavior for the same
    text — so the Both view spells out the mechanism instead of leaving it unexplained, and the
    John-native view shows no such warning since its own check (valid as plain hashcat syntax)
    is unaffected by a hashcat-compat-mode-only quirk."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"both\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 $\\xc2$\\xa3', debounced=True)
    note = driver.execute_script("return document.getElementById('portabilityNote').textContent;")
    r.check('syntax error' in note and '\\xNN byte-escape' in note and 'preprocessor' in note
            and 'valid in real hashcat and in John' in note,
            'the Both view explains the \\xNN-under-hashcat-compat-mode mechanism, not just that it fails', repr(note))

    driver.execute_script("document.querySelector('#targetBtns [data-target=\"john_native\"]').click();")
    note2 = driver.execute_script("return document.getElementById('portabilityNote').textContent;")
    bad2 = driver.execute_script("return [].map.call(document.querySelectorAll('#ruleHl .hl-bad'), function(s){ return s.textContent; });")
    r.check('Portable' in note2 and 'syntax error' not in note2 and bad2 == [],
            'the John-native view shows no warning for the same rule (not a contradiction — different mode, different check)', f'{note2!r} {bad2}')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)


def test_rule_line_underlines_the_offending_token(driver, r):
    """The portability note names what's wrong, but not where — section 02's rule line now
    underlines (wavy, red) the exact token(s) responsible, in both of the cases that can point
    at a specific step: a hashcat-only step (Hashcat view) and a step whose own token doesn't
    even parse in John's hashcat-compat mode (Both view). A plain shared step, and a step that
    merely gives a different result for this word (not a parse failure), stay unmarked — the
    tool only underlines what it can actually attribute to one step."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def bad_texts():
        return driver.execute_script(
            "return [].map.call(document.querySelectorAll('#ruleHl .hl-bad'), function(s){ return s.textContent; });")

    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'l h', debounced=True)
    r.check(bad_texts() == ['h'], 'the hashcat-only step (h) is underlined, the shared one (l) is not', f'{bad_texts()}')

    driver.execute_script("document.querySelector('#targetBtns [data-target=\"both\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 $\\xc2$\\xa3', debounced=True)
    r.check(sorted(bad_texts()) == ['$\\xa3', '$\\xc2'],
            'the token(s) John’s hashcat-compat mode refuses to parse are underlined', f'{bad_texts()}')

    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)
    r.check(bad_texts() == [], 'an ordinary, fully-portable rule has nothing underlined', f'{bad_texts()}')


def test_rule_line_has_a_custom_caret(driver, r):
    """The native text caret has no standard CSS way to be made thicker, and would sit under
    .rulehl's highlight tint anyway (that overlay paints above the input), so the real caret is
    hidden (caret-color:transparent) and a custom #fakeCaret bar is positioned in its place —
    visible, thicker, and in a color no highlight in the rule line uses. It tracks the real
    caret via the input's own selectionStart, hides during an actual (non-collapsed) selection
    and on blur, and reappears correctly positioned on refocus."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1', debounced=True)
    inp = driver.find_element('id', 'ruleTextInput')

    def caret():
        return driver.execute_script(
            "var fc = document.getElementById('fakeCaret');"
            "return {shown: getComputedStyle(fc).display !== 'none', left: parseFloat(fc.style.left) || 0};")

    r.check(driver.execute_script("return getComputedStyle(document.getElementById('ruleTextInput')).caretColor;") == 'rgba(0, 0, 0, 0)',
            'the native caret is hidden (transparent) now that a custom one replaces it')

    inp.click()
    driver.execute_script("var i=document.getElementById('ruleTextInput'); i.setSelectionRange(0,0); i.dispatchEvent(new Event('keyup',{bubbles:true}));")
    at_start = caret()
    driver.execute_script("var i=document.getElementById('ruleTextInput'); i.setSelectionRange(6,6); i.dispatchEvent(new Event('keyup',{bubbles:true}));")
    at_6 = caret()
    r.check(at_start['shown'] and at_6['shown'] and at_6['left'] > at_start['left'],
            'the fake caret is visible and moves right as the real caret moves right', f'{at_start} -> {at_6}')

    driver.execute_script("var i=document.getElementById('ruleTextInput'); i.setSelectionRange(0,3); i.dispatchEvent(new Event('select',{bubbles:true}));")
    r.check(not caret()['shown'], 'the fake caret hides during an actual text selection', f"{caret()}")

    driver.execute_script("document.getElementById('ruleTextInput').blur();")
    r.check(not caret()['shown'], 'the fake caret hides on blur', f"{caret()}")

    inp.click()
    driver.execute_script("var i=document.getElementById('ruleTextInput'); i.setSelectionRange(2,2); i.dispatchEvent(new Event('focus',{bubbles:true}));")
    r.check(caret()['shown'], 'the fake caret reappears on refocus', f"{caret()}")
    driver.execute_script("document.getElementById('ruleTextInput').blur();")


def test_both_callout_is_a_code_block(driver, r):
    """The Both setup callout is a 4-line code block plus three short
    points (not one dense paragraph)."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    # the Both setup callout: a code block and short points
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"both\"]').click();")
    time.sleep(0.2)
    cb = driver.execute_script(
        "var c = document.querySelector('#cheatBody > .callout');"
        "return {code: c.querySelector('pre.codeblock') ? c.querySelector('pre.codeblock').textContent : null, points: c.querySelectorAll('ul.calloutlist li').length};")
    r.check(cb['code'] and cb['code'].count('\n') == 3 and '!! hashcat logic ON' in cb['code'] and cb['points'] == 3,
            'the Both callout is a 4-line code block plus three short points', f'{cb}')


def test_rule_line_highlight_with_multibyte_steps(driver, r):
    """A step holding a multi-byte character (the default chain ends with Append £) is written as
    one operation per byte, so it owns several operations in the rule line. Hovering it still
    highlights all of its text, and the steps after it still line up."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)
    # make step 7 (Append !) a multi-byte character; the step after it must still match
    set_value(driver, driver.find_elements('css selector', '#chain .step')[6].find_element('css selector', '.p-arg[data-arg="X"]'), '\u00a3')
    rule = driver.execute_script("return document.getElementById('ruleTextInput').value;")
    r.check('$\\xc2$\\xa3 $1' in rule, 'editing an argument to a multi-byte character rewrites the rule line with its bytes', repr(rule))
    marks = driver.execute_script(
        "var out=[];document.querySelectorAll('#chain .step').forEach(function(c){"
        "c.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));"
        "var h=document.querySelector('#ruleHl .hl-on');out.push(h?h.textContent:null);"
        "c.dispatchEvent(new MouseEvent('mouseout',{bubbles:true}));});return out;")
    r.check(marks == ['c', 'sa4', 'se3', 'si1', 'so0', 'ss5', '$\\xc2$\\xa3', '$1'], 'hovering each step highlights exactly its own text, including the multi-byte one', repr(marks))
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)


def test_trace_keeps_a_row_for_every_step(driver, r):
    """Steps that did not run (after a rejecting step, or switched off) keep a dimmed row, so the
    trace is as long as the chain and the layout doesn't jump when the outcome changes."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'wordInput'), 'password', debounced=True)
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c >3 sa4 $1', debounced=True)
    info = lambda: driver.execute_script(
        "var rows=document.querySelectorAll('#trace .trace-row');"
        "return {n: rows.length, skipped: document.querySelectorAll('#trace .trace-row.skipped').length,"
        " rejected: document.querySelectorAll('#trace .trace-row.rejected').length,"
        " h: Math.round(document.documentElement.scrollHeight), trace: Math.round(document.getElementById('trace').getBoundingClientRect().height),"
        " why: Array.from(document.querySelectorAll('#trace .trace-row.skipped .caption')).map(function(c){return c.textContent;})};")
    ok = info()
    r.check(ok['n'] == 5 and ok['skipped'] == 0, 'a chain that finishes shows the start row and one row per step', f'{ok}')
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c >9 sa4 $1', debounced=True)   # "password" is 8 long: rejected at step 2
    rej = info()
    r.check(rej['n'] == 5 and rej['rejected'] == 1 and rej['skipped'] == 2, 'a rejection keeps a dimmed row for each later step', f'{rej}')
    r.check(all('stopped at step 2' in w for w in rej['why']), 'the dimmed rows say which step stopped the chain', f"{rej['why']}")
    r.check(rej['h'] == ok['h'] and rej['trace'] == ok['trace'], 'a rejection does not change the page or trace height', f'{ok} -> {rej}')
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 $1', debounced=True)
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[1].click();")
    off = info()
    r.check(off['skipped'] == 1 and off['why'] == ['Not run — this step is switched off'], 'a switched-off step keeps a dimmed row that says so', f'{off}')
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)


def test_cheat_legend_is_aligned(driver, r):
    """The legend's descriptions all start at the same x position (a symbol column, then a text column)."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    for target in ('hashcat', 'both', 'john_native'):
        driver.execute_script("document.querySelector('#targetBtns [data-target=\"%s\"]').click();" % target)
        xs = driver.execute_script("return Array.from(document.querySelectorAll('.legend-grid > span:not(.mono):not(.full)')).map(function(e){return Math.round(e.getBoundingClientRect().left);});")
        r.check(len(xs) >= 2 and len(set(xs)) == 1, f'the cheat sheet legend descriptions line up ({target})', f'{xs}')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")


def test_cpu_engine_chains(driver, r):
    """Memory, reject and p-position steps run in hashcat's CPU engine: the chain evaluates like
    hashcat -j (X reuses the memory buffer, p is where the last / matched), the note says so on
    its own (accent-colored) line, and the rule line underlines the responsible token(s) — same
    treatment as the Both view's syntax-error case, just a different (non-error, informational)
    color since a CPU-only step isn't broken, it just needs hashcat's other engine."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'wordInput'), 'banana', debounced=True)
    set_value(driver, driver.find_element('id', 'ruleTextInput'), '/a Dp', debounced=True)
    final = lambda: driver.execute_script("var rows=document.querySelectorAll('#trace .trace-row:not(.skipped)');return rows[rows.length-1].querySelector('.word').textContent;")
    r.check(final() == 'bnana', 'a p position deletes where the last / found its match', repr(final()))
    note_el = lambda: driver.execute_script(
        "var n = document.getElementById('portabilityNote');"
        "var cpuSpan = n.querySelector('.cpu');"
        "return {text: n.textContent, cpuSpanText: cpuSpan ? cpuSpan.textContent : null};")
    n = note_el()
    r.check('CPU engine only' in n['text'], 'the note says memory / reject / p rules run only in hashcat\'s CPU engine', repr(n))
    r.check(n['cpuSpanText'] and 'CPU engine only' in n['cpuSpanText'],
            'the CPU-only line is its own accent-colored span, not folded into another line\'s color', repr(n))
    bad_texts = lambda: driver.execute_script(
        "return [].map.call(document.querySelectorAll('#ruleHl .hl-cpu'), function(s){ return s.textContent; });")
    r.check(sorted(bad_texts()) == ['/a', 'Dp'], 'the rule line underlines the CPU-only step(s) (yellow, solid)', f'{bad_texts()}')
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'M X012 X012', debounced=True)
    r.check(final() == 'babbnana', 'X reuses the memory buffer, so a second X sees changed memory (as in hashcat)', repr(final()))
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1', debounced=True)
    n2 = note_el()
    r.check('CPU engine only' not in n2['text'] and bad_texts() == [], 'an ordinary rule gets no CPU-only note or underline', repr(n2))
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)
    set_value(driver, driver.find_element('id', 'wordInput'), 'password', debounced=True)


def test_rl_p_position_clamped_to_a_digit_for_john(driver, r):
    """R / L / p are ambiguous in John's own syntax between a hashcat op and a native command, and
    John resolves it by checking only whether the very next byte is a plain digit 0-9
    (doc/RULES-hashcat) — not a letter, not one of the named positions. Building one of these three
    for John with a letter argument would silently produce text that reads back differently, so the
    position box clamps to 0-9 there, while the same op under hashcat still allows the full 0-35."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"john_native\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'R0', debounced=True)
    set_value(driver, driver.find_element('css selector', '#chain .step .p-arg[data-arg="N"]'), '15')
    rule = driver.execute_script("return document.getElementById('ruleTextInput').value;")
    r.check(rule == 'R9', 'R\'s position clamps to 9 (a digit) for John, not 15', repr(rule))
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'R0', debounced=True)
    set_value(driver, driver.find_element('css selector', '#chain .step .p-arg[data-arg="N"]'), '15')
    rule2 = driver.execute_script("return document.getElementById('ruleTextInput').value;")
    r.check(rule2 == 'RF', 'the same op under hashcat still allows the full 0-35 range', repr(rule2))
    # p (dupeword_times) is narrower still: John's own check for it is 1-9, not 0-9 like R/L —
    # 'p0' isn't recognized as the digit form at all and fails to parse as anything sensible.
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"john_native\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'p1', debounced=True)
    set_value(driver, driver.find_element('css selector', '#chain .step .p-arg[data-arg="N"]'), '0')
    rule3 = driver.execute_script("return document.getElementById('ruleTextInput').value;")
    r.check(rule3 == 'p1', "p's position floors at 1 for John, not 0", repr(rule3))
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'p1', debounced=True)
    set_value(driver, driver.find_element('css selector', '#chain .step .p-arg[data-arg="N"]'), '0')
    rule4 = driver.execute_script("return document.getElementById('ruleTextInput').value;")
    r.check(rule4 == 'p0', 'the same op under hashcat allows 0', repr(rule4))
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)


def test_byte_escapes_in_the_rule_line(driver, r):
    """Words run as UTF-8 bytes and a rule can write a byte as \\xNN (hashcat's escape, the way to
    append a multi-byte character such as µ = c2 b5): the escapes parse, the trace shows the
    character, and a step's argument box shows a raw byte as \\xNN."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'wordInput'), 'ab', debounced=True)
    set_value(driver, driver.find_element('id', 'ruleTextInput'), '$\\xc2 $\\xb5', debounced=True)
    final = driver.execute_script("var rows=document.querySelectorAll('#trace .trace-row');return rows[rows.length-1].querySelector('.word').textContent;")
    r.check(final == 'ab\u00b5', 'the rule line "$\\xc2 $\\xb5" appends the two bytes of \u00b5', repr(final))
    arg = driver.execute_script("return document.querySelector('#chain .step .p-arg[data-arg=\"X\"]').value;")
    r.check(arg == '\\xC2', 'a raw byte shows as \\xNN in the step\'s argument box', repr(arg))
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 's\u00e9a', debounced=True)
    err = driver.execute_script("return document.getElementById('ruleError') ? document.getElementById('ruleError').textContent : (document.querySelector('.rule-error')||{}).textContent;")
    n = driver.execute_script("return document.querySelectorAll('#chain .step').length;")
    r.check(n == 0 or bool(err), 'a raw multi-byte character after s is not accepted as one-byte argument', f'{n} steps, {err!r}')
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)
    set_value(driver, driver.find_element('id', 'wordInput'), 'password', debounced=True)


def test_cheat_search_keeps_john_only_explanation(driver, r):
    """Searching the cheat sheet keeps the John-only box's explanation
    visible (a search that lands in it still says why it isn't buildable
    here), and a search with no results just says so."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"john_native\"]').click();")
    time.sleep(0.2)
    # searching keeps the John-only box's explanation; no results just says so
    set_value(driver, driver.find_element('id', 'cheatSearch'), 'single-crack')
    st = driver.execute_script(
        "var s = document.querySelector('.john-only-section');"
        "return {head: !s.querySelector('.jhead').classList.contains('cf-hide'), rows: s.querySelectorAll('.cheat-row:not(.cf-hide)').length};")
    r.check(st['head'] and st['rows'] >= 1, 'searching for a John-only command keeps the explanation of why it isn\'t buildable', f'{st}')
    set_value(driver, driver.find_element('id', 'cheatSearch'), 'zzzz')
    empty = driver.execute_script("return document.querySelector('.cheat-empty').textContent;")
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"both\"]').click();")
    time.sleep(0.2)
    set_value(driver, driver.find_element('id', 'cheatSearch'), 'zzzz')
    empty = driver.execute_script("return document.querySelector('.cheat-empty').textContent;")
    r.check(empty.startswith('No operators match') and 'John' not in empty and 'Hashcat' not in empty,
            'a search with no results just says so, without pointing at another tool', repr(empty))
    r.check(driver.execute_script("return !document.querySelector('.john-only-section');"), 'the Both view lists no John-only commands', '')
    set_value(driver, driver.find_element('id', 'cheatSearch'), '')
    driver.execute_script("document.querySelector('#targetBtns [data-target=\"hashcat\"]').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1', debounced=True)


def test_batch_table_is_a_capped_scroll_box(driver, r):
    """The batch results table is a fixed-height scroll box (about 5 rows)
    with its header pinned, so adding words no longer squeezes the trace or
    grows the columns; Expand lifts the cap (that column grows on purpose,
    the others keep their baseline) and collapsing restores it."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def words(n):
        set_value(driver, driver.find_element('id', 'batchInput'), '\n'.join('password%d' % i for i in range(1, n + 1)))
        time.sleep(0.4)

    def state():
        return driver.execute_script(
            "var h = function(id){ return Math.round(document.getElementById(id).getBoundingClientRect().height); }, sc = document.querySelector('.batch-scroll');"
            "return {cols: [h('col1Card'), h('col2Card'), h('cheatCard')], trace: h('trace'), box: Math.round(sc.getBoundingClientRect().height),"
            "        scrolls: sc.scrollHeight > sc.clientHeight + 1};")

    words(5)
    base = state()
    words(40)
    many = state()
    r.check(many['cols'] == base['cols'] and abs(many['trace'] - base['trace']) <= 2,
            'going from 5 to 40 words changes neither the column heights nor the trace list (to within rounding)', f'{base} -> {many}')
    r.check(many['scrolls'] and many['box'] <= 240, 'with 40 words the table is a short box that scrolls', f"{many['box']}px, scrolls: {many['scrolls']}")

    # header stays pinned while the rows scroll under it
    driver.execute_script("document.querySelector('.batch-scroll').scrollTop = 150;")
    time.sleep(0.15)
    pinned = driver.execute_script(
        "var sc = document.querySelector('.batch-scroll').getBoundingClientRect(), th = document.querySelector('table.batch thead th').getBoundingClientRect();"
        "return Math.abs(th.top - sc.top) <= 1;")
    r.check(pinned, 'the table header stays pinned at the top while scrolling')
    driver.execute_script("document.querySelector('.batch-scroll').scrollTop = 0;")

    # Expand: the table shows everything, its column grows, the others keep the baseline
    driver.execute_script("document.getElementById('batchExpandBtn').click();")
    time.sleep(0.4)
    ex = state()
    r.check(not ex['scrolls'] and ex['box'] > 600, 'Expand shows every row (no scrolling)', f'{ex}')
    r.check(ex['cols'][1] > many['cols'][1] and ex['cols'][0] == many['cols'][0] and ex['cols'][2] == many['cols'][2],
            'expanding grows only column 2; the other columns keep their baseline height', f"{many['cols']} -> {ex['cols']}")
    aria = driver.execute_script("var b = document.getElementById('batchExpandBtn'); return [b.getAttribute('aria-expanded'), b.getAttribute('aria-label')];")
    r.check(aria == ['true', 'Collapse batch results table'], 'the button reports its state to assistive tech', f'{aria}')
    driver.execute_script("document.getElementById('batchExpandBtn').click();")
    time.sleep(0.4)
    back = state()
    r.check(back['cols'] == many['cols'] and abs(back['trace'] - many['trace']) <= 2 and abs(back['box'] - many['box']) <= 2,
            'collapsing restores the capped table and the original layout', f'{back} vs {many}')

    # wrap off: the corner cell is pinned to the top AND the right edge
    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    driver.execute_script("var sc = document.querySelector('.batch-scroll'); sc.scrollTop = 120; sc.scrollLeft = 0;")
    time.sleep(0.15)
    corner = driver.execute_script(
        "var sc = document.querySelector('.batch-scroll').getBoundingClientRect(), th = document.querySelector('table.batch thead th:last-child').getBoundingClientRect();"
        "return {top: Math.abs(th.top - sc.top) <= 1, right: Math.abs(th.right - sc.right) <= 18};")
    r.check(corner['top'] and corner['right'], 'with wrapping off, the header and the trace column stay pinned while scrolling', f'{corner}')
    driver.execute_script("document.getElementById('batchWrap').click();")
    words(5)


def test_batch_box_shows_whole_lines_only(driver, r):
    """The batch box's height is a whole number of text lines, so no line is
    ever cut off at the bottom: by default it shows all five starter words,
    it stays whole when wrapping is toggled (the horizontal scrollbar takes
    height) or the text size changes, and dragging the resize handle snaps
    to the nearest whole line on release."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    set_value(driver, driver.find_element('id', 'batchInput'), 'password\ndragon\nsunshine\nletmein\nprincess')
    time.sleep(0.3)

    def lines():
        """visible text lines (the box's inner height / line height) and the box's scroll state"""
        return driver.execute_script(
            "var t = document.getElementById('batchInput'), cs = getComputedStyle(t), lh = parseFloat(cs.lineHeight);"
            "var inner = t.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);"
            "return {lines: Math.round(inner / lh * 100) / 100, overflow: t.scrollHeight > t.clientHeight + 1};")

    def whole(x):
        return abs(x - round(x)) < 0.05

    g = lines()
    r.check(round(g['lines']) == 5 and whole(g['lines']) and not g['overflow'], 'by default the box shows exactly 5 lines, i.e. all five starter words', f'{g}')

    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    set_value(driver, driver.find_element('id', 'batchInput'), 'password\ndragon\n' + 'x' * 120 + '\nletmein\nprincess\nsix')
    time.sleep(0.3)
    g = lines()
    r.check(whole(g['lines']), 'wrap off (a horizontal scrollbar appears): still a whole number of lines', f'{g}')
    driver.execute_script("document.getElementById('batchWrap').click();")
    time.sleep(0.3)
    g = lines()
    r.check(whole(g['lines']), 'wrap back on: still a whole number of lines', f'{g}')

    driver.execute_script("document.querySelector('[data-size-set=\"lg\"]').click();")
    time.sleep(0.4)
    g = lines()
    r.check(whole(g['lines']), 'at the larger text size: still a whole number of lines', f'{g}')
    driver.execute_script("document.querySelector('[data-size-set=\"\"]').click();")
    time.sleep(0.4)

    # simulate letting go of the resize handle after dragging the box to an arbitrary height
    driver.execute_script(
        "var t = document.getElementById('batchInput');"
        "t.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));"
        "t.style.height = (t.offsetHeight + 47) + 'px';"
        "t.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));")
    time.sleep(0.3)
    g = lines()
    r.check(whole(g['lines']) and g['lines'] >= 6, 'dragging the box taller snaps to a whole number of lines on release', f'{g}')
    driver.execute_script(
        "var t = document.getElementById('batchInput');"
        "t.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));"
        "t.style.height = '60px';"
        "t.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));")
    time.sleep(0.3)
    g = lines()
    r.check(whole(g['lines']) and g['lines'] >= 1, 'dragging it very short still leaves whole lines (at least one)', f'{g}')
    # put it back
    driver.execute_script(
        "var t = document.getElementById('batchInput');"
        "t.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));"
        "t.style.height = (t.offsetHeight + 110) + 'px';"
        "t.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));")
    time.sleep(0.3)
    set_value(driver, driver.find_element('id', 'batchInput'), 'password\ndragon\nsunshine\nletmein\nprincess')


def test_link_highlighting_switches(driver, r):
    """'Link highlights' turns the hover/focus/caret linking between the
    steps, the trace and the rule line on or off, 'Scroll to match'
    separately stops lists from being scrolled to the linked item; both are
    remembered, 'Scroll to match' is unavailable while highlights are off,
    and with the system set to reduce motion both default to off unless the
    person has chosen. Runs last (changes media emulation and storage)."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def reset():
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': ''}]})
        driver.execute_script("localStorage.removeItem('linkhl'); localStorage.removeItem('linkscroll');")
        driver.get(INDEX_URL)
        time.sleep(0.8)
        set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1 $2 $3', debounced=True)

    def pressed():
        return driver.execute_script(
            "return {hl: document.querySelector('#linkSwitch [data-link=\"highlight\"]').getAttribute('aria-pressed'),"
            "  sc: document.querySelector('#linkSwitch [data-link=\"scroll\"]').getAttribute('aria-pressed'),"
            "  scDisabled: document.querySelector('#linkSwitch [data-link=\"scroll\"]').disabled};")

    def hover_step(n):
        driver.execute_script("document.querySelectorAll('#chain .step')[arguments[0] - 1].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));", n)

    def linked():
        return driver.execute_script(
            "return {card: document.querySelectorAll('#chain .step.linked').length, row: document.querySelectorAll('#trace .trace-row.linked').length,"
            "  token: document.querySelectorAll('#ruleHl .hl-on').length};")

    try:
        reset()
        p = pressed()
        r.check(p == {'hl': 'true', 'sc': 'true', 'scDisabled': False}, 'by default both switches are on', f'{p}')
        hover_step(2)
        r.check(linked() == {'card': 1, 'row': 1, 'token': 1}, 'with highlights on, hovering a step links all three places', f'{linked()}')

        # highlights off: nothing links, 'Scroll to match' becomes unavailable
        driver.execute_script("document.querySelector('#linkSwitch [data-link=\"highlight\"]').click();")
        time.sleep(0.2)
        p = pressed()
        r.check(p['hl'] == 'false' and p['scDisabled'], 'turning highlights off also makes "Scroll to match" unavailable', f'{p}')
        r.check(linked() == {'card': 0, 'row': 0, 'token': 0}, 'an active link is cleared when highlights are turned off', f'{linked()}')
        hover_step(3)
        r.check(linked() == {'card': 0, 'row': 0, 'token': 0}, 'with highlights off, hovering a step links nothing', f'{linked()}')
        hint = driver.execute_script("return {hover: document.getElementById('hintHover').hidden, line: document.querySelector('.hoverhint').hidden};")
        r.check(hint == {'hover': True, 'line': True}, 'the "hover over a step" hint is hidden while highlights are off', f'{hint}')
        driver.execute_script("document.querySelectorAll('#chain .s-enabled')[0].focus();")
        keys = driver.execute_script("return !document.getElementById('hintKeys').hidden;")
        r.check(keys, 'the step keyboard-shortcut hint still shows when a step is focused', f'{keys}')
        driver.execute_script("document.activeElement.blur();")

        sc_state = driver.execute_script(
            "var b = document.querySelector('#linkSwitch [data-link=\"scroll\"]'); return [b.classList.contains('active'), b.getAttribute('aria-pressed')];")
        r.check(sc_state == [False, 'false'], 'while highlights are off, "Scroll to match" is drawn and reported as off, not left looking on', f'{sc_state}')

        # remembered across a reload
        driver.get(INDEX_URL)
        time.sleep(0.8)
        p = pressed()
        r.check(p['hl'] == 'false', 'the choice is remembered across a reload', f'{p}')
        driver.execute_script("document.querySelector('#linkSwitch [data-link=\"highlight\"]').click();")   # back on
        time.sleep(0.2)
        sc_back = driver.execute_script(
            "var b = document.querySelector('#linkSwitch [data-link=\"scroll\"]'); return [b.classList.contains('active'), b.getAttribute('aria-pressed'), b.disabled];")
        r.check(sc_back == [True, 'true', False], 'turning highlights back on brings "Scroll to match" back to the choice you had (on)', f'{sc_back}')

        # scrolling off: still highlights, but the lists do not move
        driver.execute_script("document.querySelector('#linkSwitch [data-link=\"scroll\"]').click();")
        time.sleep(0.2)
        set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1 so0 ss5 $! $1 $2 $3', debounced=True)
        driver.execute_script("document.getElementById('chain').scrollTop = 0; document.getElementById('trace').scrollTop = 0;")
        hover_step(1)
        driver.execute_script("document.querySelector('#trace .trace-row[data-step=\"9\"]').dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));")
        pos = driver.execute_script("return [document.getElementById('chain').scrollTop, document.getElementById('trace').scrollTop];")
        lk = linked()
        r.check(lk['card'] == 1 and lk['token'] == 1, 'with scrolling off the highlights still work', f'{lk}')
        r.check(pos == [0, 0], 'with scrolling off, hovering a trace row far down does not scroll the chain list', f'{pos}')
        driver.execute_script("document.getElementById('trace').dispatchEvent(new MouseEvent('mouseleave'));")

        # system 'reduce motion' with no saved choice: both default off; a saved choice wins
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
        driver.execute_script("localStorage.removeItem('linkhl'); localStorage.removeItem('linkscroll');")
        driver.get(INDEX_URL)
        time.sleep(0.8)
        p = pressed()
        r.check(p['hl'] == 'false' and p['sc'] == 'false', 'with the system set to reduce motion, both default to off', f'{p}')
        driver.execute_script("document.querySelector('#linkSwitch [data-link=\"highlight\"]').click();")
        time.sleep(0.2)
        driver.get(INDEX_URL)
        time.sleep(0.8)
        p = pressed()
        r.check(p['hl'] == 'true', 'an explicit choice beats the reduce-motion default (and is remembered)', f'{p}')
    finally:
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': ''}]})
        driver.execute_script("localStorage.removeItem('linkhl'); localStorage.removeItem('linkscroll');")
        driver.get(INDEX_URL)


def test_help_dialog(driver, r):
    """The help dialog (a native modal <dialog>) opens from the Help button
    or from '?' outside a text field, traps Tab inside, closes on Esc, the
    Close button or a click on the backdrop, returns focus to where it was,
    and documents the shortcuts that really exist. Real key presses."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys

    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def info():
        return driver.execute_script(
            "var d = document.getElementById('helpDialog'), a = document.activeElement;"
            "return {open: d.open, inside: d.contains(a), active: a.id || a.tagName.toLowerCase()};")

    r.check(not info()['open'], 'the help dialog starts closed')
    btn = driver.find_element('id', 'helpBtn')
    r.check(driver.execute_script("var b = document.getElementById('helpBtn'); return [b.getAttribute('aria-haspopup'), b.textContent.trim()];") == ['dialog', '? Help'],
            'the Help button is labelled and says it opens a dialog')
    btn.click()
    time.sleep(0.3)
    i = info()
    r.check(i['open'] and i['inside'], 'the Help button opens the dialog and moves focus into it', f'{i}')
    name = driver.execute_script("var d = document.getElementById('helpDialog'); return document.getElementById(d.getAttribute('aria-labelledby')).textContent;")
    r.check('shortcuts' in name.lower(), 'the dialog is labelled by its title', repr(name))

    stayed = True
    for _ in range(40):
        ActionChains(driver).send_keys(Keys.TAB).perform()
        stayed = stayed and info()['inside']
    r.check(stayed, 'Tab never leaves the dialog while it is open (focus is trapped)')
    ActionChains(driver).key_down(Keys.SHIFT).send_keys(Keys.TAB).key_up(Keys.SHIFT).perform()
    r.check(info()['inside'], 'Shift+Tab stays inside too')

    # what it documents
    text = driver.execute_script("return document.getElementById('helpDialog').textContent;")
    keys = driver.execute_script("return [].map.call(document.querySelectorAll('#helpDialog kbd'), function(k){ return k.textContent; });")
    for needle in ('Alt', 'Delete', 'Esc', 'Tab', 'Space'):
        r.check(needle in keys, f'the dialog documents the {needle} key', f'{keys}')
    shortcuts = driver.execute_script("return document.querySelector('#chain .s-enabled').getAttribute('aria-keyshortcuts');")
    r.check(all(k in shortcuts for k in ('Alt+ArrowUp', 'Alt+ArrowDown', 'Delete')) and 'Alt' in keys and '\u2191' in text and '\u2193' in text,
            "the shortcuts in the dialog match the ones a step's checkbox advertises", f'{shortcuts!r}')

    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    time.sleep(0.3)
    r.check(not info()['open'] and info()['active'] == 'helpBtn', 'Esc closes the dialog and focus returns to the Help button', f'{info()}')

    # '?' from the page
    driver.find_element('tag name', 'body').click()
    ActionChains(driver).send_keys('?').perform()
    time.sleep(0.3)
    r.check(info()['open'], 'pressing ? opens the dialog', f'{info()}')
    driver.execute_script("document.getElementById('helpClose').click();")
    time.sleep(0.2)
    r.check(not info()['open'], 'the Close button closes it')

    # '?' inside a text box must just type a question mark
    box = driver.find_element('id', 'cheatSearch')
    box.click()
    ActionChains(driver).send_keys('?').perform()
    time.sleep(0.2)
    r.check(not info()['open'] and box.get_attribute('value') == '?', "typing ? in a text box types a question mark and does not open the dialog", f"{info()}, value {box.get_attribute('value')!r}")
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    time.sleep(0.2)
    r.check(box.get_attribute('value') == '' and not info()['open'], 'Esc in the cheat sheet search clears it (as the dialog says), without opening anything', f"{box.get_attribute('value')!r}")

    # a click on the dimmed backdrop closes it
    driver.execute_script("document.getElementById('helpBtn').click();")
    time.sleep(0.3)
    driver.execute_script("document.getElementById('helpDialog').dispatchEvent(new MouseEvent('click', {bubbles: true}));")   # target is the dialog itself = the backdrop
    time.sleep(0.2)
    r.check(not info()['open'], 'clicking the backdrop closes it')
    driver.find_element('tag name', 'body').click()


def test_section_gaps_are_consistent(driver, r):
    """The small description lines under the section headings are followed by
    the same 16px gap as everything else in a card (they once kept the
    browser's default paragraph margin and left 29px), and a status line
    with no text takes no room at all."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    # a chain-side edit clears the 'Loaded N operations' line left over from typing a rule earlier
    driver.execute_script("var c = document.querySelector('#chain .s-enabled'); c.click(); document.querySelector('#chain .s-enabled').click();")
    time.sleep(0.2)
    gaps = driver.execute_script(
        "var R = function(e){ return e.getBoundingClientRect(); }, q = function(s){ return document.querySelector(s); };"
        "var gap = function(a, b){ return Math.round(R(b).top - R(a).bottom); };"
        "return {desc02: gap(q('#ruleLineSub'), q('.rulewrap')),"
        "        desc03: gap(q('#h-chain').closest('.sectionhead').nextElementSibling, q('#chain')),"
        "        row04: gap(q('.traceopts'), q('#trace')),"
        "        desc05: gap(q('#col2Card .sub'), q('#batchBox')),"
        "        head01: gap(q('#h-word'), q('#wordInput')),"
        "        note: gap(q('.rulewrap'), q('#portabilityNote')),"
        "        noteToHeading: gap(q('#portabilityNote'), q('#h-chain').closest('.sectionhead'))};")
    for name in ('desc02', 'desc03', 'row04', 'desc05'):
        r.check(abs(gaps[name] - gaps['head01']) <= 1, f'gap after the {name} text/row equals the normal 16px gap', f"{gaps}")
    r.check(gaps['note'] < gaps['head01'], 'the portability note sits closer to the rule line it describes', f"{gaps}")
    r.check(gaps['noteToHeading'] <= 14, 'the next section heading sits close under the portability note (not a big empty gap)', f"{gaps}")
    pos = driver.execute_script("return [getComputedStyle(document.getElementById('ruleParseStatus')).position, document.getElementById('ruleParseStatus').textContent === ''];")
    r.check(pos == ['absolute', True], 'an empty status line takes no room (but stays in the accessibility tree)', f'{pos}')


def test_top_bar_buttons_are_uniform(driver, r):
    """Every button in the top bar (views, theme, text size, link switches,
    help) is the same height, and so is every group around them, at all
    three text sizes — the text-size "A" buttons used to be taller."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()

    def heights():
        return driver.execute_script(
            "var rnd = function(x){ return Math.round(x * 10) / 10; };"
            "return {buttons: Array.from(new Set([].map.call(document.querySelectorAll('.controlrow .mbtn'), function(b){ return rnd(b.getBoundingClientRect().height); }))),"
            "        groups: Array.from(new Set([].map.call(document.querySelectorAll('.controlrow > div'), function(g){ return rnd(g.getBoundingClientRect().height); })))};")

    for size, label in (('', 'default'), ('lg', 'larger'), ('xl', 'largest')):
        driver.execute_script("document.querySelector('#sizeSwitch [data-size-set=\"' + arguments[0] + '\"]').click();", size)
        time.sleep(0.3)
        h = heights()
        r.check(len(h['buttons']) == 1 and len(h['groups']) == 1, f'{label} text size: all top-bar buttons and groups are one height', f'{h}')
    driver.execute_script("document.querySelector('#sizeSwitch [data-size-set=\"\"]').click();")
    driver.find_element('css selector', '.mbtn[data-mode="validator"]').click()
    h = heights()
    r.check(len(h['buttons']) == 1 and len(h['groups']) == 1, 'the same in the validator view', f'{h}')
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()


def test_top_bar_stays_within_the_intro_width(driver, r):
    """The top bar is no wider than the intro text below it, so the display
    switches (views, theme, text size) fill the first row and high contrast,
    the link switches and Help wrap to a second row."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    info = driver.execute_script(
        "var row = document.querySelector('.controlrow'), top0 = row.getBoundingClientRect().top;"
        "var lead = document.querySelector('#builderIntro .lead').getBoundingClientRect();"
        "var g = [].map.call(row.children, function(x){ var b = x.getBoundingClientRect(); return {id: x.id || x.className.split(' ').pop(), row: Math.round(b.top - top0), right: Math.round(b.right)}; });"
        "return {leadRight: Math.round(lead.right), barRight: Math.max.apply(null, g.map(function(x){ return x.right; })), g: g};")
    r.check(info['barRight'] <= info['leadRight'], 'the top bar does not stick out past the intro paragraph', f"{info['barRight']} vs {info['leadRight']}")
    first = {x['id'] for x in info['g'] if x['row'] == info['g'][0]['row']}
    second = {x['id'] for x in info['g'] if x['row'] != info['g'][0]['row']}
    r.check(first == {'modeToggle', 'themeSwitch', 'sizeSwitch'} and second == {'contrastswitch', 'linkSwitch', 'helpgroup'},
            'views, theme and text size share the first row; high contrast, the link switches and Help are on the second', f'{info["g"]}')


CONTRAST_JS = """
function parse(c){var m=(c||'').match(/rgba?\\(([^)]+)\\)/); if(!m) return null; var p=m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1};}
function over(f,b){return {r:f.r*f.a+b.r*(1-f.a),g:f.g*f.a+b.g*(1-f.a),b:f.b*f.a+b.b*(1-f.a),a:1};}
function lum(c){var f=function(v){v/=255; return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4);}; return .2126*f(c.r)+.7152*f(c.g)+.0722*f(c.b);}
function cr(a,b){var x=lum(a),y=lum(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
function bgOf(el){var chain=[]; for(var e=el;e;e=e.parentElement){var c=parse(getComputedStyle(e).backgroundColor); if(c&&c.a>0){chain.push(c); if(c.a>=1) break;}}
  var base=parse(getComputedStyle(document.body).backgroundColor)||{r:255,g:255,b:255,a:1}; if(base.a<1) base={r:255,g:255,b:255,a:1};
  for(var i=chain.length-1;i>=0;i--) base=over(chain[i],base); return base;}
function vis(e){var r=e.getBoundingClientRect(),c=getComputedStyle(e); return r.width>0&&r.height>0&&c.visibility!=='hidden'&&c.display!=='none'&&!e.closest('[hidden]')&&!e.closest('.skipnav')&&!e.closest('.sr-only');}
var minText=arguments[0], minLargeText=arguments[1], minBorder=arguments[2];
var badText=[], seen={};
var w=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n;
while(n=w.nextNode()){
  var t=n.textContent.trim(); if(!t) continue; var el=n.parentElement;
  if(el.tagName==='SCRIPT'||el.tagName==='STYLE'||!vis(el)) continue;
  if(el.closest('button:disabled,input:disabled,select:disabled,[aria-disabled=true]')) continue;   // disabled controls are exempt
  var cs=getComputedStyle(el), o=1; for(var e=el;e;e=e.parentElement) o*=parseFloat(getComputedStyle(e).opacity);
  var fg=parse(cs.color), b=bgOf(el), f=over({r:fg.r,g:fg.g,b:fg.b,a:fg.a*o},b), size=parseFloat(cs.fontSize), bold=parseInt(cs.fontWeight)>=700;
  var large=size>=24||(size>=18.66&&bold), ratio=cr(f,b), need=large?minLargeText:minText;
  var key=el.tagName+'.'+el.className+'|'+cs.color+'|'+o+'|'+JSON.stringify(b); if(seen[key]) continue; seen[key]=1;
  if(ratio<need) badText.push(ratio.toFixed(2)+' (need '+need+') '+t.slice(0,24)+' ['+String(el.className||el.tagName).slice(0,20)+']');
}
var badBorder=[], seenB={};
[].forEach.call(document.querySelectorAll('button,input:not([type=checkbox]):not([type=hidden]),select,textarea'), function(el){
  if(!vis(el)||el.disabled) return; var cs=getComputedStyle(el), par=bgOf(el.parentElement||document.body);
  var bw=parseFloat(cs.borderTopWidth)||0, bc=parse(cs.borderTopColor), bg=parse(cs.backgroundColor);
  var border=(bw>0&&bc&&bc.a>0)?cr(over(bc,par),par):0, fill=(bg&&bg.a>0)?cr(over(bg,par),par):0;
  if(!bw && el.closest('.modetoggle,.targetbtns')) return;       // a segment of a switch: the group's own border is the control edge (checked below)
  var key=el.tagName+'.'+String(el.className).split(' ')[0]+Math.round(border*10)+Math.round(fill*10); if(seenB[key]) return; seenB[key]=1;
  if(Math.max(border,fill)<minBorder) badBorder.push(Math.max(border,fill).toFixed(2)+' '+el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+'.'+String(el.className).split(' ')[0]);
});
[].forEach.call(document.querySelectorAll('.modetoggle,.targetbtns'), function(g){
  if(!vis(g)) return; var cs=getComputedStyle(g), par=bgOf(g.parentElement), bc=parse(cs.borderTopColor); var r=cr(over(bc,par),par);
  if(r<minBorder) badBorder.push(r.toFixed(2)+' switch group #'+(g.id||g.className.split(' ').pop()));
});
return {text: badText, borders: badBorder};
"""


def _contrast_scan(driver):
    """Run the contrast scan in the states that carry the rarest colors: the
    builder (with a disabled step, an error, the undo toast, the cheat
    sheet expanded), each target, the help dialog and the validator."""
    driver.find_element('css selector', '.mbtn[data-mode="builder"]').click()
    driver.execute_script("document.getElementById('cheatExpandBtn').click();")
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'c sa4 se3 si1', debounced=True)
    driver.execute_script("document.querySelectorAll('#chain .s-enabled')[1].click();")           # a disabled step
    driver.execute_script("document.querySelectorAll('#chain .step .del')[0].click();")           # shows the undo toast
    set_value(driver, driver.find_element('id', 'ruleTextInput'), 'zzz', debounced=True)          # an error state
    return driver, set_value


def test_contrast(driver, r, mode, min_text, min_large, min_border):
    """Both themes, in the given contrast mode: every piece of visible text
    in the rare-color states, and the edge of every bordered control."""
    import time as _t
    for theme in ('dark', 'light'):
        driver.execute_script("localStorage.clear();")
        driver.get(INDEX_URL)
        _t.sleep(0.7)
        driver.execute_script("document.querySelector('#themeSwitch [data-theme-set=\"' + arguments[0] + '\"]').click();", theme)
        if mode == 'high':
            driver.execute_script("document.getElementById('contrastBtn').click();")
        _t.sleep(0.3)
        problems = {'text': [], 'borders': []}

        def scan():
            res = driver.execute_script(CONTRAST_JS, min_text, min_large, min_border)
            problems['text'] += res['text']
            problems['borders'] += res['borders']

        _contrast_scan(driver)
        scan()
        for target in ('both', 'john_native'):
            driver.execute_script("document.querySelector('#targetBtns [data-target=\"' + arguments[0] + '\"]').click();", target)
            _t.sleep(0.3)
            scan()
        driver.execute_script("document.getElementById('helpBtn').click();")
        _t.sleep(0.3)
        scan()
        driver.execute_script("document.getElementById('helpDialog').close();")
        driver.execute_script("document.querySelector('.mbtn[data-mode=\"validator\"]').click();")
        set_value(driver, driver.find_element('id', 'validatorInput'), 'c sa4\nzzz\n# a comment', debounced=True)
        scan()
        text, borders = sorted(set(problems['text'])), sorted(set(problems['borders']))
        r.check(not text, f'{theme} theme, {mode} contrast: all text reaches {min_text}:1 ({min_large}:1 for large text)', f'{len(text)} below: {text[:6]}')
        r.check(not borders, f'{theme} theme, {mode} contrast: every control edge reaches {min_border}:1', f'{len(borders)} below: {borders[:6]}')
    driver.execute_script("localStorage.clear();")
    driver.get(INDEX_URL)


def test_contrast_meets_wcag_aa(driver, r):
    """WCAG 2.2 AA in both themes: text 4.5:1 (3:1 large) and 1.4.11
    non-text contrast, 3:1 for the edge of every control."""
    test_contrast(driver, r, 'normal', 4.5, 3, 3)


def test_high_contrast_meets_wcag_aaa(driver, r):
    """High contrast, in both themes: all text reaches 7:1 (4.5:1 large,
    WCAG AAA) and every control edge 4.5:1."""
    test_contrast(driver, r, 'high', 7, 4.5, 4.5)


def test_high_contrast_switch(driver, r):
    """The High contrast switch toggles the stronger palette on either
    theme, reports its state, is remembered, and with no saved choice
    follows the system's 'more contrast' setting (an explicit choice wins).
    Runs last (changes media emulation and storage)."""
    import time as _t

    def state():
        return driver.execute_script(
            "var b = document.getElementById('contrastBtn');"
            "return {attr: document.documentElement.dataset.contrast || null, pressed: b.getAttribute('aria-pressed'), active: b.classList.contains('active'),"
            "        dim: getComputedStyle(document.documentElement).getPropertyValue('--dim').trim()};")

    def system(value):
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-contrast', 'value': value}]})
        _t.sleep(0.2)

    try:
        system('')
        driver.execute_script("localStorage.clear();")
        driver.get(INDEX_URL)
        _t.sleep(0.7)
        normal = state()
        r.check(normal['attr'] is None and normal['pressed'] == 'false', 'high contrast is off by default', f'{normal}')
        driver.execute_script("document.getElementById('contrastBtn').click();")
        _t.sleep(0.2)
        high = state()
        r.check(high['attr'] == 'high' and high['pressed'] == 'true' and high['active'] and high['dim'] != normal['dim'],
                'the switch turns it on, swaps the palette and reports pressed', f'{normal["dim"]} -> {high["dim"]}')
        driver.execute_script("document.querySelector('#themeSwitch [data-theme-set=\"light\"]').click();")
        _t.sleep(0.2)
        light = state()
        r.check(light['attr'] == 'high' and light['dim'] != high['dim'], 'it works together with the light theme (its own palette)', f'{light}')
        driver.get(INDEX_URL)
        _t.sleep(0.7)
        r.check(state()['attr'] == 'high', 'the choice is remembered across a reload (applied before first paint)', f'{state()}')
        driver.execute_script("document.getElementById('contrastBtn').click();")   # off, explicitly
        _t.sleep(0.2)

        # system 'more contrast' with no saved choice -> on; an explicit choice wins
        driver.execute_script("localStorage.clear();")
        system('more')
        driver.get(INDEX_URL)
        _t.sleep(0.7)
        sysmore = state()
        r.check(sysmore['attr'] == 'high' and sysmore['pressed'] == 'true', 'with the system asking for more contrast and no saved choice, it starts on', f'{sysmore}')
        driver.execute_script("document.getElementById('contrastBtn').click();")   # the person turns it off
        _t.sleep(0.2)
        driver.get(INDEX_URL)
        _t.sleep(0.7)
        r.check(state()['attr'] is None, 'an explicit "off" beats the system setting (and is remembered)', f'{state()}')
    finally:
        system('')
        driver.execute_script("localStorage.clear();")
        driver.get(INDEX_URL)


def test_forced_colors_keep_states_visible(driver, r):
    """In forced-colors mode (Windows High Contrast) the browser drops
    backgrounds and shadows, so the active toggle and the linked-step
    highlights must also be drawn with outlines. Runs last (media emulation)."""
    import time as _t
    try:
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'forced-colors', 'value': 'active'}]})
        driver.get(INDEX_URL)
        _t.sleep(0.8)

        def outline(sel):
            return driver.execute_script(
                "var e = document.querySelector(arguments[0]); if (!e) return null; var cs = getComputedStyle(e);"
                "return [cs.outlineStyle, parseFloat(cs.outlineWidth)];", sel)

        act = outline('#themeSwitch .mbtn.active')
        idle = outline('#themeSwitch .mbtn:not(.active)')
        r.check(act[0] != 'none' and act[1] >= 2 and idle[0] == 'none', 'forced colors: the active toggle has an outline and the inactive ones do not', f'{act} vs {idle}')
        driver.execute_script("document.querySelectorAll('#chain .step')[1].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));")
        _t.sleep(0.2)
        card, row, tok = outline('#chain .step.linked'), outline('#trace .trace-row.linked'), outline('#ruleHl .hl-on')
        r.check(all(x and x[0] != 'none' and x[1] >= 2 for x in (card, row, tok)), 'forced colors: the linked card, trace row and rule-line token are outlined', f'{card} {row} {tok}')
        grip = driver.execute_script("var cs = getComputedStyle(document.querySelector('#chain .grip'), '::before'); return cs.backgroundImage.indexOf('gradient') >= 0;")
        r.check(grip, 'forced colors: the drag handle dots are still drawn', f'{grip}')
    finally:
        driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'forced-colors', 'value': ''}]})
        driver.get(INDEX_URL)


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
        test_final_trace_row_still_highlights_when_pinned(driver, r)
        test_scroll_to_show_clears_row_near_the_end_when_locked(driver, r)
        test_rule_line_hover_links_its_step(driver, r)
        test_rule_line_caret_links_its_step(driver, r)
        test_batch_rows_keep_their_line_numbers(driver, r)
        test_batch_wrap_toggle(driver, r)
        test_batch_box_line_number_gutter(driver, r)
        test_batch_table_is_a_capped_scroll_box(driver, r)
        test_batch_box_shows_whole_lines_only(driver, r)
        test_lists_keep_their_scroll_position(driver, r)
        test_compat_operators_have_a_non_color_marker(driver, r)
        test_native_compat_dialog_opens_and_closes(driver, r)
        test_target_views_are_consistent(driver, r)
        test_section_gaps_are_consistent(driver, r)
        test_both_view_warns_when_john_would_differ(driver, r)
        test_both_view_explains_the_hex_escape_syntax_error(driver, r)
        test_rule_line_underlines_the_offending_token(driver, r)
        test_rule_line_has_a_custom_caret(driver, r)
        test_both_callout_is_a_code_block(driver, r)
        test_cheat_search_keeps_john_only_explanation(driver, r)
        test_page_has_no_phantom_scroll(driver, r)
        test_columns_stay_equal_height(driver, r)
        test_tall_window_shrinks_chain_instead_of_padding_trace(driver, r)
        test_columns_refit_on_window_resize(driver, r)
        test_reduced_motion_is_respected(driver, r)
        test_auto_theme_follows_the_system(driver, r)
        test_link_highlighting_switches(driver, r)
        test_help_dialog(driver, r)
        test_rl_p_position_clamped_to_a_digit_for_john(driver, r)
        test_byte_escapes_in_the_rule_line(driver, r)
        test_cpu_engine_chains(driver, r)
        test_cheat_legend_is_aligned(driver, r)
        test_trace_keeps_a_row_for_every_step(driver, r)
        test_rule_line_highlight_with_multibyte_steps(driver, r)
        test_top_bar_buttons_are_uniform(driver, r)
        test_top_bar_stays_within_the_intro_width(driver, r)
        test_contrast_meets_wcag_aa(driver, r)
        test_high_contrast_meets_wcag_aaa(driver, r)
        test_high_contrast_switch(driver, r)
        test_forced_colors_keep_states_visible(driver, r)
        test_validator_inline_edit_live_reparse(driver, r)
        test_validator_restore(driver, r)
        test_validator_dialect_switch_reparses_and_preserves_deletions(driver, r)
    finally:
        driver.quit()

    return r.summarize()


if __name__ == '__main__':
    sys.exit(main())
