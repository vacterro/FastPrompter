import json
import sys

log_path = r'C:\Users\vac34\.gemini\antigravity\brain\2c7a476c-ab4c-4162-9b3f-29a92e3c1f4d\.system_generated\logs\transcript_full.jsonl'
try:
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            if data.get('type') == 'PLANNER_RESPONSE':
                if 'tool_calls' in data:
                    for call in data['tool_calls']:
                        if call['name'] in ('replace_file_content', 'write_to_file', 'run_command', 'multi_replace_file_content'):
                            args = call.get('args', {})
                            content = str(args)
                            if 'open_saipen_dialog' in content and 'main.py' in content:
                                print(f"Found in step {data.get('step_index')}:")
                                print(call['name'])
                                if 'ReplacementContent' in args:
                                    print("--- REPLACEMENT CONTENT ---")
                                    print(args['ReplacementContent'])
                                elif 'CodeContent' in args:
                                    print("--- CODE CONTENT ---")
                                    print(args['CodeContent'])
                                elif 'CommandLine' in args:
                                    print("--- COMMAND LINE ---")
                                    print(args['CommandLine'])
except Exception as e:
    print(f"Error: {e}")
