"""Journal grading return contract, without live provider calls."""
from . import test


@test("ARIA quality grader skips missing evidence", tier=1, features=['config'], mode='local')
def test_journal_quality_contract():
    from utilities.aria_journal_quality import grade_render, parse_grade
    assert grade_render({}, {}, {}) == {
        'status': 'skipped', 'reason': 'missing render or vision evidence'}
    assert parse_grade('{"assessable":true,"score":0,"reason":"Mismatch"}')['score'] == 0
    return True
