import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.services.chat_agent import HtmlEditSession, run_agent_loop, restore_resume_messages, build_static_system_prompt
from app.services.source_agent import create_source_workspace
from tests.test_agent_loop_end_to_end import ScriptedChatModel


def run(model, session, **kwargs):
    async def go():
        return [event async for event in run_agent_loop(model, '源码测试', session.html, '只改首行缩进',
            create_source_workspace(session).map_payload(), None, [], session=session, tool_protocol='v2', **kwargs)]
    return asyncio.run(go())


class SourceAgentTests(unittest.TestCase):
    def test_pause_after_write_resumes_from_checkpoint_revision(self):
        from app.api.routes.chat import _user_question_source_html
        from fastapi import HTTPException
        from app.services.html_workspace import HtmlWorkspace
        source = '<p>甲🙂</p>'
        checkpoints = []
        session = HtmlEditSession(source, checkpoint_callback=checkpoints.append)
        model = ScriptedChatModel(script=[{'tool': ('edit_file', {'path': '/article.html',
            'revision': session.source_file().revision, 'edits': [{'old_text': '甲', 'new_text': '乙'}]})},
            {'tool': ('ask_user', {'question': '接下来选什么？', 'options': []})}], seen_messages=[], seen_message_counts=[])
        data = run(model, session)[-1]['data']
        self.assertEqual(checkpoints[-1], '<p>乙🙂</p>')
        self.assertEqual(data['source_revision'], HtmlWorkspace.revision_for(checkpoints[-1]))
        saved = {'tool_protocol': 'v2', 'current_html': checkpoints[-1], 'source_revision': data['source_revision']}
        restarted_source = _user_question_source_html(saved, checkpoints[-1])
        restarted = HtmlEditSession(restarted_source)
        resumed = ScriptedChatModel(script=[{'tool': ('edit_file', {'path': '/article.html',
            'revision': data['source_revision'], 'edits': [{'old_text': '乙', 'new_text': '丙'}]})}, {'text': '完成。'}],
            seen_messages=[], seen_message_counts=[])
        done = run(resumed, restarted, resume_messages=restore_resume_messages(data['resume_messages']),
            resume_tool_result={'tool_call_id': data['tool_call_id'], 'content': '继续'})
        self.assertEqual(done[-1]['event'], 'final')
        self.assertEqual(restarted.html, '<p>丙🙂</p>')
        self.assertEqual(_user_question_source_html({'current_html': source}, source), source)
        for saved_record, actual in [(saved, source), ({**saved, 'source_revision': 'corrupt'}, checkpoints[-1])]:
            with self.assertRaises(HTTPException) as error:
                _user_question_source_html(saved_record, actual)
            self.assertEqual(error.exception.status_code, 409)

    def test_reference_reads_survive_article_change_and_article_offsets_expire(self):
        from app.services.agent_context import ContextRecord
        def record(name, content):
            return ContextRecord(id=1, message_id=1, kind='tool', document_revision='old',
                payload={'name': name, 'content': json.dumps(content, ensure_ascii=False)})
        reference = {'path': '/reference.html', 'readonly': True, 'revision': 'reference',
                     'start': 0, 'end': 9, 'content': '<p>参考</p>'}
        self.assertEqual(json.loads(record('read_file', reference)._stale_tool_content('new', 4096)), reference)
        article = {**reference, 'path': '/article.html', 'readonly': False, 'before_start': 2, 'before_end': 3}
        stale = json.loads(record('read_file', article)._stale_tool_content('new', 4096))
        self.assertTrue(stale['stale'])
        self.assertNotIn('before_start', stale['historical_result'])
        self.assertNotIn('<p>参考</p>', stale['historical_result'])

    def test_loaded_image_group_executes_inventory_with_source_editing_guidance(self):
        session = HtmlEditSession('<p><img src="https://example.invalid/photo.png"></p>')
        model = ScriptedChatModel(script=[{'tool': ('enable_tool_groups', {'groups': ['images']})},
            {'tool': ('inspect_current_images', {})}, {'text': '完成。'}], seen_messages=[], seen_message_counts=[])
        results = [json.loads(event['data']['model_input']['content']) for event in run(model, session)
                   if event['event'] == 'tool_result']
        self.assertEqual(results[1]['image_count'], 1)
        self.assertIn('edit_file', model.bound_tool_names)
        self.assertNotIn('apply_html_patch', model.bound_tool_names)

    def test_unloaded_and_legacy_tools_are_rejected_without_mutation(self):
        session = HtmlEditSession('<p>正文</p>')
        model = ScriptedChatModel(script=[{'tool': ('replace_document', {'revision': session.source_file().revision,
            'html': '<p>禁止的写入</p>'})}, {'tool': ('generate_article_images', {'prompt': 'picture'})},
            {'text': '完成。'}], seen_messages=[], seen_message_counts=[])
        events = run(model, session)
        failures = [event['data'] for event in events if event['event'] == 'tool_result']
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(not json.loads(item['model_input']['content'])['ok'] for item in failures))
        self.assertEqual(session.html, '<p>正文</p>')

    def test_continuation_rejects_stale_revision_after_write(self):
        session = HtmlEditSession('<p>' + '甲🙂' * 1000 + '</p>')
        revision = session.source_file().revision
        model = ScriptedChatModel(script=[{'tool': ('read_file', {'path': '/article.html', 'max_tokens': 320})},
            {'tool': ('edit_file', {'path': '/article.html', 'revision': revision,
                'edits': [{'old_text': '甲', 'new_text': '乙', 'replace_all': True}]})},
            {'tool': ('read_file', {'path': '/article.html', 'cursor': 10, 'revision': revision})},
            {'text': '完成。'}], seen_messages=[], seen_message_counts=[])
        results = [json.loads(event['data']['model_input']['content']) for event in run(model, session)
                   if event['event'] == 'tool_result']
        self.assertFalse(results[0]['complete'])
        self.assertTrue(results[1]['ok'])
        self.assertFalse(results[2]['ok'])

    def test_preflight_state_matches_runtime_on_supported_and_legacy_providers(self):
        from app.services import chat_agent as agent
        for provider, enabled in [('openai_responses', True), ('openai_compatible', False), ('anthropic', True)]:
            source = '<p>中文🙂</p>'
            selected = [{'selector': 'p:nth-of-type(1)', 'tag_name': 'p', 'text': '中文🙂'}]
            reference = {'html': '<p>参考</p>', 'imitation_strength': 'maximum'}
            model_config = SimpleNamespace(prompt_cache_enabled=enabled, tool_result_max_tokens=4096,
                                           provider=SimpleNamespace(provider_type=SimpleNamespace(value=provider)))
            factory = agent.runtime_context_budget_factory(model_config, '源码测试', source,
                selected_elements=selected, layout_reference=reference, tool_protocol='v2')
            fixed, volatile = factory({})
            model = ScriptedChatModel(script=[{'text': '完成。'}], seen_messages=[], seen_message_counts=[])
            run(model, HtmlEditSession(source), selected_elements=selected, layout_reference=reference,
                prompt_cache_enabled=enabled, provider_type=provider)
            outgoing = model.seen_messages[0]
            if agent._uses_stable_prompt_prefix(enabled, provider):
                self.assertEqual(outgoing[0].content, fixed)
                self.assertEqual(outgoing[-1].content, volatile)
            else:
                self.assertIn(volatile.removeprefix(agent._RUNTIME_CONTEXT_HEADER), outgoing[0].content)
            self.assertIn('maximum', volatile)
            self.assertNotIn('block_id', volatile)

    def test_source_compaction_retains_revision_and_complete_tool_pairs(self):
        from app.services import chat_agent as agent
        from tests.test_run_compaction import _assert_tool_pairing, _cycle
        session = HtmlEditSession('<p>最新正文</p>')
        pending = AIMessage(content='', tool_calls=[{'id': 'question', 'name': 'ask_user', 'args': {}}])
        resume = [SystemMessage(content='旧系统'), HumanMessage(content='只改首行缩进'),
                  *(message for i in range(8) for message in _cycle(i, payload_blocks=3)), pending]
        compactor = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
            field: '保留完成调整' if field == 'completed' else '' for field in agent._RUNTIME_SUMMARY_FIELDS}))))
        factory = agent.runtime_context_budget_factory(SimpleNamespace(prompt_cache_enabled=True,
            tool_result_max_tokens=4096, provider=SimpleNamespace(provider_type=SimpleNamespace(value='openai_responses'))),
            '源码测试', session.html, tool_protocol='v2')
        fixed, volatile = factory({})
        budget = sum(agent._provider_message_tokens(message, agent.PROVIDER_TOKEN_ESTIMATE_SAFETY_MULTIPLIER)
                     for message in [SystemMessage(content=fixed), HumanMessage(content=volatile), resume[1], *resume[-6:]]) + 1500
        model = ScriptedChatModel(script=[{'text': '完成。'}], seen_messages=[], seen_message_counts=[])
        with patch.object(agent, '_agent_tool_schema_tokens', return_value=0):
            events = run(model, session, prompt_cache_enabled=True, provider_type='openai_responses',
                resume_messages=resume, resume_tool_result={'tool_call_id': 'question', 'content': '确认'},
                compaction_model=compactor, run_input_budget_tokens=budget)
        self.assertEqual(events[-1]['event'], 'final')
        compactor.ainvoke.assert_awaited_once()
        outgoing = model.seen_messages[0]
        self.assertIn(session.source_file().revision, outgoing[-1].content)
        self.assertEqual(sum(agent._is_runtime_context(message) for message in outgoing), 1)
        _assert_tool_pairing(self, outgoing[:-1])

    def test_selected_indent_needs_one_write_and_final_response(self):
        source = '<p style="text-indent:0;color:red">保留🙂</p>'
        session = HtmlEditSession(source)
        model = ScriptedChatModel(script=[{'tool': ('edit_file', {'path': '/article.html',
            'revision': session.source_file().revision, 'edits': [{'old_text': 'text-indent:0', 'new_text': 'text-indent:2em'}]})},
            {'text': '已调整。'}], seen_messages=[], seen_message_counts=[])
        events = run(model, session, selected_elements=[{'selector': 'p:nth-of-type(1)', 'tag_name': 'p', 'text': '保留🙂'}])
        self.assertEqual(session.html, source.replace('text-indent:0', 'text-indent:2em'))
        self.assertEqual(len(model.seen_messages), 2)
        self.assertNotIn('apply_html_patch', model.bound_tool_names)
        self.assertNotIn('generate_article_images', model.bound_tool_names)
        self.assertIn('edit_file', model.bound_tool_names)
        result = next(event['data'] for event in events if event['event'] == 'tool_result')
        self.assertEqual(result['html'], session.html)
        self.assertTrue(json.loads(result['model_input']['content'])['ok'])
        self.assertIn(session.source_file().revision, str(model.seen_messages[-1][0].content))

    def test_source_prompt_has_no_mandatory_block_chain(self):
        prompt = build_static_system_prompt('v2')
        self.assertIn('read_file', prompt)
        self.assertNotIn('search_html', prompt)
        self.assertNotIn('read_blocks', prompt)
        self.assertNotIn('block_id', prompt)

    def test_query_reads_reference_and_history_is_readonly(self):
        session = HtmlEditSession('<p>正文</p>')
        model = ScriptedChatModel(script=[{'tool': ('read_file', {'path': '/reference.html'})},
            {'tool': ('write_file', {'path': '/reference.html', 'revision': 'anything', 'content': 'change'})},
            {'text': '参考已读取。'}], seen_messages=[], seen_message_counts=[])
        events = run(model, session, layout_reference={'html': '<section><p>只读参考</p></section>'})
        results = [json.loads(event['data']['model_input']['content']) for event in events if event['event'] == 'tool_result']
        self.assertIn('只读参考', results[0]['content'])
        self.assertFalse(results[1]['ok'])
        self.assertEqual(session.html, '<p>正文</p>')
        self.assertEqual(session.workspace_metrics()['index_builds'], 0)

    def test_diff_edit_commits_checkpoint_and_validation_warning_can_be_repaired(self):
        checkpoints = []
        session = HtmlEditSession('<p>正文</p>', checkpoint_callback=checkpoints.append)
        initial_revision = session.source_file().revision
        candidate = '<p>正文</section>'
        from app.services.html_workspace import HtmlWorkspace
        model = ScriptedChatModel(script=[{'tool': ('edit_file', {'path': '/article.html', 'revision': initial_revision,
            'edits': [{'old_text': '</p>', 'new_text': '</section>'}]})},
            {'tool': ('edit_file', {'path': '/article.html', 'revision': HtmlWorkspace.revision_for(candidate),
            'edits': [{'old_text': '</section>', 'new_text': '</p>'}]})}, {'text': '完成。'}],
            seen_messages=[], seen_message_counts=[])
        events = run(model, session)
        results = [json.loads(event['data']['model_input']['content']) for event in events if event['event'] == 'tool_result']
        self.assertIsNotNone(results[0]['warning'])
        self.assertIsNone(results[1]['warning'])
        self.assertIn(candidate, checkpoints)
        self.assertEqual(session.html, '<p>正文</p>')

    def test_stable_prompt_refreshes_source_revision_and_pairs_tool_messages(self):
        session = HtmlEditSession('<p>甲</p>')
        from app.services.html_workspace import HtmlWorkspace
        after_first = '<p>乙</p>'
        model = ScriptedChatModel(script=[{'tool': ('edit_file', {'path': '/article.html', 'revision': session.source_file().revision,
            'edits': [{'old_text': '甲', 'new_text': '乙'}]})}, {'tool': ('edit_file', {'path': '/article.html',
            'revision': HtmlWorkspace.revision_for(after_first), 'edits': [{'old_text': '乙', 'new_text': '丙'}]})},
            {'text': '完成。'}], seen_messages=[], seen_message_counts=[])
        events = run(model, session, prompt_cache_enabled=True, provider_type='openai_responses')
        self.assertEqual(session.html, '<p>丙</p>')
        self.assertEqual(model.seen_messages[0][0].content, model.seen_messages[-1][0].content)
        self.assertIn(session.source_file().revision, str(model.seen_messages[-1][-1].content))
        self.assertEqual(sum(isinstance(message, ToolMessage) for message in model.seen_messages[-1]), 2)
        self.assertEqual(events[-1]['event'], 'final')

    def test_tool_groups_survive_pause_and_restart(self):
        session = HtmlEditSession('<p>正文</p>')
        model = ScriptedChatModel(script=[{'tool': ('enable_tool_groups', {'groups': ['images']})},
            {'tool': ('ask_user', {'question': '采用哪种图片？', 'options': []})}], seen_messages=[], seen_message_counts=[])
        events = run(model, session)
        data = events[-1]['data']
        self.assertEqual(events[-1]['event'], 'user_question')
        self.assertEqual(data['tool_protocol'], 'v2')
        self.assertEqual(data['loaded_tool_groups'], ['images'])
        resumed = ScriptedChatModel(script=[{'text': '已继续。'}], seen_messages=[], seen_message_counts=[])
        done = run(resumed, HtmlEditSession(session.html), loaded_tool_groups=data['loaded_tool_groups'],
            resume_messages=restore_resume_messages(data['resume_messages']),
            resume_tool_result={'tool_call_id': data['tool_call_id'], 'content': '{"answer":"A"}'})
        self.assertIn('view_article_images', resumed.bound_tool_names)
        self.assertNotIn('apply_html_patch', resumed.bound_tool_names)
        self.assertEqual(done[-1]['event'], 'final')

    def test_browser_check_is_optional_and_failures_preserve_write(self):
        for requested in [False, True]:
            checkpoints = []
            session = HtmlEditSession('<p>甲</p>', checkpoint_callback=checkpoints.append)
            model = ScriptedChatModel(script=[{'tool': ('edit_file', {'path': '/article.html', 'revision': session.source_file().revision,
                'edits': [{'old_text': '甲', 'new_text': '乙'}], 'check_wechat': requested})}, {'text': '已修改。'}],
                seen_messages=[], seen_message_counts=[])
            with patch.object(session, 'check_compliance', side_effect=RuntimeError('browser unavailable')) as check:
                events = run(model, session)
                self.assertEqual(check.call_count, int(requested))
            self.assertEqual(session.html, '<p>乙</p>')
            self.assertIn(session.html, checkpoints)
            payload = json.loads(next(event['data']['model_input']['content'] for event in events if event['event'] == 'tool_result'))
            self.assertTrue(payload['ok'])
            if requested:
                self.assertIsNone(payload['compliance']['isValid'])


if __name__ == '__main__':
    unittest.main()
