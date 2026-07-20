import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Show context
for i in range(732, min(738, len(lines))):
    print(f'{i+1}: {repr(lines[i])}')

# Fix line 734 (index 733): merge the two-line tooltip into one line
# Current: '            "Toggle Sidebar\n'
#          'Show or hide the sidebar containing snippets and silos."\n'
# Fix: put it all on one line with literal \n escape

lines[733] = '            "Toggle Sidebar\\nShow or hide the sidebar containing snippets and silos."\n'
del lines[734]  # Remove the orphaned next line

with open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Fixed")

# Verify
import ast
ast.parse(open('main.py', encoding='utf-8').read())
print("Syntax OK")
