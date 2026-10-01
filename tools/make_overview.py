import json

data = json.load(open('all_untranslated_context.json', encoding='utf-8'))

with open('untranslated_overview.txt', 'w', encoding='utf-8') as f:
    for i, d in enumerate(data, 1):
        f.write(f"[{i}] KEY: {repr(d['key'])}\n")
        if d['ru']:
            f.write(f"    RU : {repr(d['ru'])}\n")
        if d['de']:
            f.write(f"    DE : {repr(d['de'])}\n")
        f.write(f"    SPA: {d['spa']}, PT: {d['pt']}\n\n")

print(f"Written untranslated_overview.txt with {len(data)} items")
