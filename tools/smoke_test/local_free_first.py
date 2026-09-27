"""Offline return-type and fallback checks for plaintext routing."""
from . import test


@test('Plaintext helpers use free pool before paid fallback', tier=1, features=['config'], mode='local')
def test_free_first_text():
    from unittest.mock import patch
    from utilities.free_first_text import free_first_text, validate_context
    from utilities import kumori_api_client
    with patch.object(kumori_api_client, 'llm_chat_resilient', return_value=('{}', 'free', [], None)) as free:
        result = free_first_text(messages=[{'role': 'user', 'content': 'fixture'}],
                                 model='unused', max_tokens=20, feature='test', validate=validate_context)
        assert isinstance(result, str) and result == '{}'
        assert free.call_count == 1
        assert free.call_args.kwargs['retry_on_5xx'] is False
    return True


@test('Plaintext paid fallback rejects empty output and preserves attribution', tier=1, features=['config'], mode='local')
def test_free_first_fallback():
    import sys
    from types import ModuleType, SimpleNamespace
    from unittest.mock import Mock, patch
    from utilities import kumori_api_client
    from utilities.free_first_text import free_first_text, validate_context
    logger = ModuleType('utilities.anthropic_logger')
    logger.logged_create = Mock(return_value=SimpleNamespace(content=[SimpleNamespace(text='{}')]))
    pricing = ModuleType('utilities.anthropic.pricing')
    pricing.sampling_kwargs = lambda model, temperature: {'temperature': temperature}
    with patch.dict(sys.modules, {'utilities.anthropic_logger': logger, 'utilities.anthropic.pricing': pricing}), \
            patch.object(kumori_api_client, 'llm_chat_resilient', side_effect=RuntimeError('exhausted')) as free:
        args = dict(messages=[{'role': 'user', 'content': 'fixture'}], model='fixture',
                    max_tokens=20, feature='test', user_id=42, validate=validate_context)
        assert free_first_text(**args) == '{}'
        assert free.call_count == 1
        assert free.call_args.kwargs['budget_ms'] == 15000
        assert logger.logged_create.call_args.kwargs['user_id'] == '42'
        assert logger.logged_create.call_args.kwargs['app_name'] == 'galactica'
        for content in ([], [SimpleNamespace(type='thinking')], [SimpleNamespace(text='{"code":1}')]):
            logger.logged_create.return_value.content = content
            try:
                free_first_text(**args)
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid paid output was accepted')
    return True


@test('Bug extraction returns structured errors without writing invalid reports', tier=1, features=['config'], mode='local')
def test_bug_extraction_failures():
    import importlib.util
    import sys
    from pathlib import Path
    from types import ModuleType
    from unittest.mock import Mock, patch
    pricing = ModuleType('utilities.anthropic.pricing')
    pricing.CLAUDE_MODELS = {}
    core = ModuleType('utilities.postgres.core')
    core.db_cursor = Mock(side_effect=AssertionError('No DB access allowed'))
    storage = ModuleType('utilities.pilgrimbot_utils')
    storage.get_chat_history = Mock(return_value=[{'role': 'user', 'content': 'Fixture bug'}])
    bugs = ModuleType('utilities.postgres.bugs')
    bugs.create_bug = Mock(side_effect=AssertionError('Invalid report must not be written'))
    bugs.add_bug_comment = Mock()
    path = Path(__file__).resolve().parents[2] / 'utilities/pilgrimbot_bugs.py'
    with patch.dict(sys.modules, {'utilities.anthropic.pricing': pricing, 'utilities.postgres.core': core,
                                 'utilities.pilgrimbot_utils': storage, 'utilities.postgres.bugs': bugs}):
        spec = importlib.util.spec_from_file_location('bug_extraction_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for error in (ValueError('invalid JSON/schema'), RuntimeError('both providers unavailable')):
            with patch.object(module, 'free_first_text', side_effect=error):
                assert module.create_bug_from_response('fixture', 42)['success'] is False
                assert module.create_bug_from_conversation('fixture-chat', 42)['success'] is False
        core.db_cursor.assert_not_called()
        bugs.create_bug.assert_not_called()
        bugs.add_bug_comment.assert_not_called()
    return True
