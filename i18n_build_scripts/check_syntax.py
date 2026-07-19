"""Find syntax error in gen_no.py."""
text = open("V:\\_TEMP_\\opencode\\gen_no.py", encoding="utf-8").read()
lines = text.split("\n")
# Find the first line where TR starts (line 22, 0-indexed 21)
# Search for lines with potential mismatched quotes
for i, line in enumerate(lines):
    if i < 21:
        continue
    if i > 30:
        break
    # Try compiling just up to this line + context
    partial = "\n".join(lines[:i+50])
    try:
        compile(partial, "check", "exec")
    except SyntaxError as e:
        if "never closed" in str(e):
            print(f"Error zone around line {i+1}")
            for j in range(max(0,i-2), min(len(lines), i+10)):
                print(f"  {j+1}: {lines[j][:120]}")
            break
