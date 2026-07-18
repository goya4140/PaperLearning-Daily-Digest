import pytest

from paper_digest.delivery import resolve_provider


@pytest.mark.parametrize(
    ("sender", "expected"),
    [
        ("reader@gmail.com", "gmail"),
        ("reader@qq.com", "qq"),
        ("reader@163.com", "163"),
        ("reader@126.com", "163"),
    ],
)
def test_auto_smtp_provider(sender, expected):
    assert resolve_provider("auto", sender) == expected


def test_explicit_smtp_provider_is_preserved():
    assert resolve_provider("qq", "reader@example.com") == "qq"
