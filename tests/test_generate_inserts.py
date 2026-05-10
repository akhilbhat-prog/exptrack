from generate_inserts import escape


def test_none_returns_null():
    assert escape(None) == "NULL"

def test_plain_string():
    assert escape("hello") == "'hello'"

def test_string_with_apostrophe():
    assert escape("it's") == "'it''s'"

def test_integer():
    assert escape(42) == "'42'"

def test_float():
    assert escape(3.14) == "'3.14'"

def test_empty_string():
    assert escape("") == "''"

def test_multiple_apostrophes():
    assert escape("can't won't") == "'can''t won''t'"

def test_sql_injection_attempt():
    result = escape("'; DROP TABLE transactions; --")
    assert "DROP TABLE" in result
    assert result.startswith("'")
    assert result.endswith("'")
    assert "''" in result  # apostrophe was escaped
