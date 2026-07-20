import ast

with open('V:/___VAC/__K/__CODE/_PY/_FastPrompter/src/fastprompter/core/i18n/tln.py', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# Check for lines with problematic apostrophes in single-quoted strings
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if not stripped.startswith("'") and not stripped.startswith('"'):
        continue
    # Count single quotes - if odd number, there's a problem
    single_quotes = [j for j, c in enumerate(stripped) if c == "'"]
    # Find pairs of single quotes that might enclose the key and value
    if len(single_quotes) > 2:
        # Check if value starts with single quote
        colon_pos = stripped.find("':")
        if colon_pos > 0:
            val_start = stripped.find("'", colon_pos + 2)
            if val_start > 0:
                remaining = stripped[val_start:]
                # Count quotes in remaining
                remaining_quotes = [j for j, c in enumerate(remaining) if c == "'"]
                if len(remaining_quotes) % 2 != 0:
                    print(f"Line {i}: odd quotes in value")
                    print(f"  {stripped[:150]}")

print("---")

# Try to compile
try:
    ast.parse(content)
    print("AST OK")
except SyntaxError as e:
    print(f"SyntaxError line {e.lineno}: {e.msg}")
    # Show context
    for j in range(max(0, e.lineno-3), min(len(lines), e.lineno+2)):
        marker = ">>>" if j+1 == e.lineno else "   "
        print(f"{marker} {j+1}: {lines[j][:120]}")
