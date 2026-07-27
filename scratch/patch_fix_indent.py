import os
import glob

target_files = ["tests_smoke\\test_send_selection.py", "tests_smoke\\test_settings_layout.py"]

for filepath in target_files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # The file has bad indentation starting at `w.hide()`
    # Let's fix the 4 spaces.
    lines = content.split('\n')
    fixed_lines = []
    in_bad_block = False
    for line in lines:
        if "w.conn = None" in line and "w.state.conn" not in line:
            fixed_lines.append(line)
            in_bad_block = True
            continue
        if in_bad_block and "def test_" in line:
            in_bad_block = False
            
        if in_bad_block:
            if line.startswith("    w.") or line.startswith("    if ") or line.startswith("        ") or line.startswith("    from") or line.startswith("    QApp") or line.startswith("    QCore"):
                fixed_lines.append(line)
            elif line.startswith("w.hide()"):
                fixed_lines.append("    w.hide()")
            elif line.startswith("# "):
                fixed_lines.append("    " + line)
            elif line.startswith("if "):
                fixed_lines.append("    " + line)
            elif line.startswith("w.deleteLater()"):
                fixed_lines.append("    w.deleteLater()")
            elif line.startswith("from "):
                fixed_lines.append("    " + line)
            elif line.startswith("QApp") or line.startswith("QCore"):
                fixed_lines.append("    " + line)
            elif line.startswith("    "):
                fixed_lines.append(line)
            elif line.strip() == "":
                fixed_lines.append("")
            else:
                fixed_lines.append("    " + line)
        else:
            fixed_lines.append(line)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(fixed_lines))
    print(f"Fixed indentation in {filepath}")
