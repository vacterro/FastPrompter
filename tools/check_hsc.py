with open('src/fastprompter/main.py', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        for c in ['"H"', '"S"', '"C"']:
            if c in line and ('self.tr' in line or 'tr(' in line or '_(' in line or 'QAction' in line or 'QPushButton' in line):
                print(f'{i}: {line.strip()}')
