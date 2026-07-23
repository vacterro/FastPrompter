import json
import sys

log_path = r'C:\Users\vac34\.gemini\antigravity\brain\2c7a476c-ab4c-4162-9b3f-29a92e3c1f4d\.system_generated\logs\transcript_full.jsonl'
try:
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if 'open_saipen_dialog' in line and 'def ' in line:
                data = json.loads(line)
                if data.get('type') == 'PLANNER_RESPONSE':
                    print(f"Found in step {data.get('step_index')}")
                    for call in data.get('tool_calls', []):
                        if 'open_saipen_dialog' in str(call):
                            print(call['name'])
                            args = call.get('args', {})
                            for k, v in args.items():
                                if 'open_saipen_dialog' in str(v):
                                    print(f'-- {k} --')
                                    print(str(v)[:500])
except Exception as e:
    print(f'Error: {e}')
