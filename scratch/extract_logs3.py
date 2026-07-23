import json
import sys

log_path = r'C:\Users\vac34\.gemini\antigravity\brain\2c7a476c-ab4c-4162-9b3f-29a92e3c1f4d\.system_generated\logs\transcript_full.jsonl'
try:
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if 'btn_saipen' in line:
                data = json.loads(line)
                if data.get('type') == 'PLANNER_RESPONSE':
                    print(f"Found btn_saipen in step {data.get('step_index')}")
except Exception as e:
    pass
