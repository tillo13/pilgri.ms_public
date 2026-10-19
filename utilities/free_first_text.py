"""Plain-text helpers only; PilgrimBot's tool loop keeps its existing transport."""
import json
import logging

logger = logging.getLogger(__name__)


def parse_json(text, expected_type):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    parsed = json.loads(text)
    if not isinstance(parsed, expected_type):
        raise ValueError('Unexpected JSON response type')
    return parsed


def validate_context(text):
    plan = parse_json(text, dict)
    for key, value in plan.items():
        if key in ('endgame', 'bugs') and type(value) is bool:
            continue
        if key in ('math', 'code', 'player_data', 'brainstorm') and isinstance(value, list) and all(isinstance(v, str) for v in value):
            continue
        raise ValueError('Invalid context plan field')


def validate_bug(text):
    bug = parse_json(text, dict)
    if any(not isinstance(bug.get(k), str) or not bug[k].strip()
           for k in ('title', 'description', 'priority', 'evidence')):
        raise ValueError('Incomplete bug report')
    if bug['priority'] not in ('P1', 'P2', 'P3') or not isinstance(bug.get('affected_areas', ''), str):
        raise ValueError('Invalid bug report fields')


def validate_related(text):
    for bug in parse_json(text, list):
        if (not isinstance(bug, dict) or type(bug.get('id')) is not int
                or not isinstance(bug.get('reason'), str) or not bug['reason'].strip()):
            raise ValueError('Invalid related-bug entry')


def free_first_text(*, messages, model, max_tokens, feature, system=None,
                    temperature=0.3, user_id=None, validate=None):
    def checked(text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Empty completion')
        if validate:
            validate(text)
        return text.strip()

    try:
        from utilities.kumori_api_client import llm_chat_resilient
        text, _, _, _ = llm_chat_resilient(
            messages=messages, system=system, max_tokens=max_tokens, temperature=temperature,
            min_quality_tier='medium', allow_degrade=True, budget_ms=15000,
            min_chars=1, app_name='galactica', retry_on_5xx=False)
        return checked(text)
    except Exception as exc:
        logger.warning('%s free attempt failed (%s); trying Claude', feature, type(exc).__name__)

    from utilities.anthropic_logger import logged_create
    from utilities.anthropic.pricing import sampling_kwargs
    kwargs = dict(model=model, max_tokens=max_tokens, messages=messages, **sampling_kwargs(model, temperature))
    if system:
        kwargs['system'] = system
    response = logged_create(app_name='galactica', feature=feature,
                             user_id=str(user_id) if user_id else 'system:galactica_pilgrimbot',
                             **kwargs)
    text = next((block.text for block in (response.content or [])
                 if isinstance(getattr(block, 'text', None), str)), '')
    return checked(text)
