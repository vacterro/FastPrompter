import ast, json

def py_val(s):
    has_single = "'" in s
    has_double = '"' in s
    if has_single and not has_double:
        return json.dumps(s, ensure_ascii=False)
    elif has_double and not has_single:
        return repr(s)
    else:
        return json.dumps(s, ensure_ascii=False)

tests = [
    'Hei',
    "It's fine",
    'Quotemark: "hello"',
    "Both 'single' and \"double\"",
    'Line1\nLine2',
    'Tab\there',
    "Pagina's",
    "How should '{}' be added?",
]
for t in tests:
    v = py_val(t)
    parsed = ast.literal_eval(v)
    assert parsed == t, f'{parsed!r} != {t!r}'
    print(f'OK: {v}')
print('All tests passed')
