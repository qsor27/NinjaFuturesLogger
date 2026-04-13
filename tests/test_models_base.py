from models.base import StrictModel


def test_strict_model_rejects_unknown_fields():
    class Foo(StrictModel):
        a: int

    try:
        Foo(a=1, b=2)
    except Exception:
        return
    raise AssertionError("expected validation error for unknown field 'b'")


def test_strict_model_rejects_type_coercion():
    class Foo(StrictModel):
        a: int

    try:
        Foo(a="1")
    except Exception:
        return
    raise AssertionError("expected validation error: str passed where int required")
