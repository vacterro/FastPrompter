"""Binary search for syntax error in TR dict."""
text = open("V:\\_TEMP_\\opencode\\gen_no.py", encoding="utf-8").read()

# Find TR = { start and end
start = text.index("TR = {")
end = text.index("}", start) + 1  # first closing brace
while end < len(text) and text[end] == "\n":
    # try to find the actual closing brace for TR dict
    # Just search for the line that is just "}"
    pass

# Split into lines
lines = text.split("\n")
tr_start = None
tr_end = None
for i, line in enumerate(lines):
    if line.strip() == "TR = {":
        tr_start = i
    if tr_start is not None and line.strip() == "}":
        tr_end = i
        break

print(f"TR dict lines: {tr_start+1} to {tr_end+1}")

# Test progressively
for i in range(tr_start, tr_end + 1):
    snippet = "\n".join(lines[:i+1]) + "\n}"
    try:
        compile(snippet + "\nx = 1", "check", "exec")
    except SyntaxError as e:
        print(f"Error at line {i+1}: {e.msg}")
        print(f"  {lines[i][:150]}")
        break
