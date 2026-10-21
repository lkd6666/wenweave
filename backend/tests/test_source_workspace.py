import difflib
import json
import unittest
from unittest.mock import patch

from app.services.chat_agent import HtmlEditSession
from app.services.html_workspace import WorkspaceError
from app.services.source_agent import create_source_workspace, source_selections
from app.services.source_workspace import SourceFile, SourceWorkspace, apply_replacements, apply_unified_diff, fit_file_page, read_source, search_source, search_files_source
from app.services.token_budget import estimate_tokens


class SourceWorkspaceTests(unittest.TestCase):
    def test_changed_ranges_address_new_source_after_length_changes(self):
        actual, summary = apply_replacements('甲🙂乙丙', [{'old_text': '甲', 'new_text': '开始'},
            {'old_text': '丙', 'new_text': '结束🙂'}])
        self.assertEqual(actual, '开始🙂乙结束🙂')
        self.assertEqual([(actual[item['start']:item['end']], item['before_start'], item['before_end'])
                          for item in summary['changes']], [('开始', 0, 1), ('结束🙂', 3, 4)])

    def test_file_directory_pages_keep_entries_and_fit_actual_envelope(self):
        entries = [SourceFile(f'/templates/{i}.html', '甲🙂').metadata() for i in range(50)]
        seen, cursor = [], 0
        while cursor is not None:
            page = fit_file_page(entries[cursor:], cursor, None, 320, history_directory='/history')
            self.assertLessEqual(estimate_tokens(json.dumps(page, ensure_ascii=False, separators=(',', ':'))), 320)
            seen.extend(page['files'])
            self.assertTrue(page['files'])
            cursor = page['next_cursor']
        self.assertEqual(seen, entries)

    def test_multi_file_search_envelope_and_individual_cursors_fit_budget(self):
        files = [SourceFile(f'/templates/{i}.html', '甲🙂' * 50) for i in range(3)]
        result = search_files_source(files, '甲', budget=1600, context_chars=2)
        self.assertLessEqual(estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(',', ':'))), 1600)
        self.assertTrue(all(item['matches'] and item['next_cursor'] is not None for item in result['files']))
        with self.assertRaises(WorkspaceError):
            search_files_source(files, '甲', budget=100)

    def test_diff_unicode_line_separator_is_source_content(self):
        source = '甲\u2028🙂\n乙\n'
        diff = '--- a/article.html\n+++ b/article.html\n@@ -1,2 +1,2 @@\n 甲\u2028🙂\n-乙\n+丙\n'
        self.assertEqual(apply_unified_diff(source, diff)[0], '甲\u2028🙂\n丙\n')

    def test_component_move_and_article_reconstruction_preserve_source(self):
        source = '<section>\r\n<p>甲🙂</p>\r\n<section><p>组件</p></section>\r\n<p>乙</p>\r\n</section>'
        component = '<section><p>组件</p></section>\r\n'
        moved, _ = apply_replacements(source, [{'old_text': component, 'new_text': ''},
            {'old_text': '<p>甲🙂</p>\r\n', 'new_text': component + '<p>甲🙂</p>\r\n'}])
        self.assertEqual(moved, '<section>\r\n' + component + '<p>甲🙂</p>\r\n<p>乙</p>\r\n</section>')
        session = HtmlEditSession(source)
        session.write_source(session.source_file().revision, moved)
        self.assertEqual(session.html, moved)

    def test_diagnostics_use_visible_unicode_source_positions_after_inline_image(self):
        session = HtmlEditSession('<p><img src="data:image/png;base64,' + 'A' * 400 + '">甲🙂</wrong></p>')
        report = session.source_validation(session.validate_html())
        issue = next(item for item in report.issues if item.tag == 'wrong')
        self.assertEqual(issue.column, session.source_file().content.index('</wrong>') + 1)
        self.assertEqual(issue.line, 1)

    def test_reads_lines_without_serializing_source(self):
        file = SourceFile('/article.html', '<p>甲🙂</p>\r\n<p>乙</p>\r\n')
        result = read_source(file, start_line=2, end_line=2)
        self.assertEqual(result['content'], '<p>乙</p>\r\n')
        self.assertEqual(result['start'], len('<p>甲🙂</p>\r\n'))
        with self.assertRaises(WorkspaceError):
            read_source(file, start=0, start_line=1)

    def test_oversized_single_line_can_be_read_to_completion(self):
        source = '<section>' + '<p>保留🙂</p>' * 1000 + '</section>'
        file = SourceFile('/article.html', source)
        parts, cursor = [], None
        while True:
            result = read_source(file, cursor=cursor, budget=500)
            self.assertLessEqual(estimate_tokens(json.dumps(result, ensure_ascii=False, separators=(',', ':'))), 500)
            parts.append(result['content'])
            cursor = result['next_cursor']
            if cursor is None:
                break
        self.assertEqual(''.join(parts), source)

    def test_search_long_line_returns_exact_offsets_and_bounded_context(self):
        source = '甲🙂' * 5000 + 'Text-Indent' + '乙' * 5000
        result = search_source(SourceFile('/article.html', source), 'text-indent', case_sensitive=False, context_chars=5)
        match = result['matches'][0]
        self.assertEqual(match['start'], 10000)
        self.assertEqual(source[match['start']:match['end']], 'Text-Indent')
        self.assertEqual(len(match['content']), len('Text-Indent') + 10)

    def test_search_pages_repeated_matches(self):
        file = SourceFile('/article.html', '匹配' * 50)
        found, cursor = [], 0
        while True:
            result = search_source(file, '匹配', cursor=cursor, limit=7)
            found.extend(item['start'] for item in result['matches'])
            cursor = result['next_cursor']
            if cursor is None:
                break
        self.assertEqual(found, list(range(0, 100, 2)))

    def test_edits_repeated_source_only_with_explicit_scope_or_replace_all(self):
        source = '<p>甲</p><p>甲</p>'
        with self.assertRaises(WorkspaceError):
            apply_replacements(source, [{'old_text': '甲', 'new_text': '乙'}])
        scoped, _ = apply_replacements(source, [{'old_text': '甲', 'new_text': '乙', 'start': 8}])
        self.assertEqual(scoped, '<p>甲</p><p>乙</p>')
        all_edits, summary = apply_replacements(source, [{'old_text': '甲', 'new_text': '乙', 'replace_all': True}])
        self.assertEqual(all_edits, '<p>乙</p><p>乙</p>')
        self.assertEqual(summary['operation_count'], 2)

    def test_multiple_edits_share_snapshot_and_can_cross_tag_boundaries(self):
        source = '<p>甲</p><p>乙</p>'
        changed, _ = apply_replacements(source, [{'old_text': '</p><p>', 'new_text': ' / '},
                                               {'old_text': '乙', 'new_text': '🙂乙'}])
        self.assertEqual(changed, '<p>甲 / 🙂乙</p>')
        with self.assertRaises(WorkspaceError):
            apply_replacements(source, [{'old_text': '<p>甲</p>', 'new_text': 'x'}, {'old_text': '甲', 'new_text': 'y'}])

    def test_diff_multiple_hunks_preserves_crlf(self):
        source = 'alpha\r\nbeta\r\ngamma\r\ndelta\r\nepsilon\r\n'
        expected = source.replace('alpha', 'ALPHA').replace('epsilon', 'EPSILON')
        diff = ''.join(difflib.unified_diff(source.splitlines(keepends=True), expected.splitlines(keepends=True),
                                         fromfile='a/article.html', tofile='b/article.html', n=1))
        actual, _ = apply_unified_diff(source, diff)
        self.assertEqual(actual, expected)
        with self.assertRaises(WorkspaceError):
            apply_unified_diff(source, diff.replace('-alpha', '-stale'))

    def test_diff_preserves_missing_final_newline_and_inserts_at_end(self):
        source = 'alpha\nbeta'
        diff = '--- a/article.html\n+++ b/article.html\n@@ -2 +2 @@\n-beta\n\\ No newline at end of file\n+BETA\n\\ No newline at end of file\n'
        self.assertEqual(apply_unified_diff(source, diff)[0], 'alpha\nBETA')
        insert = '--- a/article.html\n+++ b/article.html\n@@ -1,0 +2 @@\n+beta\n'
        self.assertEqual(apply_unified_diff('alpha\n', insert)[0], 'alpha\nbeta\n')

    def test_diff_repeated_context_retains_correct_mixed_endings(self):
        diff = '--- a/article.html\n+++ b/article.html\n@@ -1,2 +1 @@\n-x\n x\n'
        self.assertEqual(apply_unified_diff('x\r\nx\n', diff)[0], 'x\n')

    def test_diff_rejects_foreign_file_and_invalid_hunk_counts(self):
        for diff in ['--- a/reference.html\n+++ b/reference.html\n@@ -1 +1 @@\n-x\n+y\n',
                     '--- a/article.html\n+++ b/article.html\n@@ -1,2 +1 @@\n-x\n+y\n']:
            with self.assertRaises(WorkspaceError):
                apply_unified_diff('x\n', diff)

    def test_virtual_files_cannot_escape_registered_namespace(self):
        session = HtmlEditSession('<p>正文</p>')
        workspace = create_source_workspace(session, layout_reference={'html': '<p>参考</p>'},
                                            attached_templates=[{'id': 3, 'html': '<p>组件</p>'}])
        self.assertFalse(workspace.get('/article.html').readonly)
        self.assertTrue(workspace.get('/reference.html').readonly)
        for name in ['../article.html', 'C:/secret.txt', '/templates/4.html', '/history/1.html']:
            with self.assertRaises(WorkspaceError):
                workspace.get(name)

    def test_source_commit_keeps_inline_data_and_builds_no_dom_index(self):
        source = '<p style="text-indent:0">甲🙂<img src="data:image/png;base64,ORIGINAL"></p>'
        session = HtmlEditSession(source)
        visible = session.source_file()
        self.assertNotIn('ORIGINAL', visible.content)
        with patch('app.services.chat_agent.validate_html_structure', wraps=__import__('app.services.chat_agent', fromlist=['validate_html_structure']).validate_html_structure) as validate:
            summary = session.edit_source(visible.revision, [{'old_text': 'text-indent:0', 'new_text': 'text-indent:2em'}])
            session.validate_html()
            self.assertEqual(validate.call_count, 1)
        self.assertEqual(session.html, source.replace('text-indent:0', 'text-indent:2em'))
        self.assertEqual(session.workspace_metrics()['index_builds'], 0)
        restarted = HtmlEditSession(session.html)
        self.assertEqual(restarted.source_file().content, session.source_file().content)
        self.assertNotEqual(summary['revision'], visible.revision)

    def test_rejects_stale_revision_unknown_tokens_and_atomic_failed_batch(self):
        session = HtmlEditSession('<p>甲乙</p>')
        revision = session.source_file().revision
        for edits in [[{'old_text': '甲', 'new_text': 'x'}, {'old_text': '不存在', 'new_text': 'y'}],
                      [{'old_text': '甲', 'new_text': '__YIBAN_INLINE_DATA_unknown__'}],
                      [{'old_text': '甲', 'new_text': '__YIBAN_INLINE_DATA_unknown-with-dash__'}],
                      [{'old_text': '甲', 'new_text': '__YIBAN_INLINE_DATA_incomplete'}]]:
            with self.assertRaises(WorkspaceError):
                session.edit_source(revision, edits)
            self.assertEqual(session.html, '<p>甲乙</p>')
        with self.assertRaises(WorkspaceError):
            session.edit_source('stale', [{'old_text': '甲', 'new_text': 'x'}])

    def test_selection_offsets_address_redacted_source_and_inline_nodes(self):
        session = HtmlEditSession('<p><img src="data:image/png;base64,SECRET">甲<span style="color:red">乙</span></p>')
        selected = source_selections(session, [{'selector': 'p:nth-of-type(1) > span:nth-of-type(1)',
                                                'tag_name': 'span', 'text': '乙'}])[0]
        visible = session.source_file().content
        self.assertEqual(visible[selected['start']:selected['end']], selected['content'])
        self.assertTrue(selected['content'].startswith('<span'))

    def test_cancel_and_strict_validator_prevent_commit(self):
        session = HtmlEditSession('<p>甲</p>', cancel_requested=lambda: True)
        with self.assertRaises(WorkspaceError):
            session.write_source(session.source_file().revision, '<p>乙</p>')
        strict = HtmlEditSession('<p>甲</p>', candidate_validator=lambda _: (_ for _ in ()).throw(WorkspaceError('strict')))
        with self.assertRaises(WorkspaceError):
            strict.write_source(strict.source_file().revision, '<p>乙</p>')
        self.assertEqual(strict.html, '<p>甲</p>')


if __name__ == '__main__':
    unittest.main()
