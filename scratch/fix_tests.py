import glob, re
for f in glob.glob('tests_smoke/test_*.py'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    content = content.replace('scope="module"', 'scope="function"')
    
    # ensure w.deleteLater() is in teardown
    if 'w.deleteLater()' not in content:
        content = re.sub(r'(w\.conn = None\s*\n)', r'\1    w.deleteLater()\n', content)
        
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
print('Done!')
