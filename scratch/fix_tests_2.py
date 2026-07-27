import glob, re
for f in glob.glob('tests_smoke/test_*.py'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # We already changed to function scope. But we need to add processEvents()
    if 'w.deleteLater()' in content and 'QApplication.processEvents()' not in content:
        content = content.replace('w.deleteLater()', 'w.deleteLater()\n    QApplication.processEvents()')
        
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
print('Done!')
