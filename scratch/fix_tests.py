import glob
import re

for filepath in glob.glob('tests/test_*.py'):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = re.sub(r'sys\.modules\[\"PyQt6.*?\] = .*?\n', '', content)
    new_content = re.sub(r'sys\.modules\[\"pynput.*?\] = .*?\n', '', new_content)
    new_content = re.sub(r'sys\.modules\[\'PyQt6.*?\] = .*?\n', '', new_content)
    new_content = re.sub(r'sys\.modules\[\'pynput.*?\] = .*?\n', '', new_content)
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'Stripped sys.modules patches from {filepath}')
