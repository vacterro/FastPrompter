import os
script_abs = os.path.abspath(r'V:\___VAC\__K\__CODE\_PY\_WR\WildRiftAssistant\wr_runtime.ahk').replace('\\', '\\\\')
ps_cmd = (
    "Get-CimInstance Win32_Process -Filter \"name like '%AutoHotkey%'\" | "
    "Where-Object {{ $_.CommandLine -like '*{script}*' }} | "
    "Select-Object -ExpandProperty ProcessId"
).format(script=script_abs)
print("POWERSHELL CMD:")
print(ps_cmd)
print("---")
assert '%A' not in ps_cmd, "STILL HAS %A!"
print("OK - no %A conflict")
assert script_abs in ps_cmd, "script_abs not found"
print("OK - script_abs in cmd")
