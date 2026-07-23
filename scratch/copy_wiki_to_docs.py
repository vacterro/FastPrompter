import os
import shutil

src_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\subs\saiwiki\wiki"
dst_dir = r"V:\___VAC\__K\__CODE\_PY\_FastPrompter\docs\wiki"

os.makedirs(dst_dir, exist_ok=True)

for filename in os.listdir(src_dir):
    src_file = os.path.join(src_dir, filename)
    dst_file = os.path.join(dst_dir, filename)
    if os.path.isfile(src_file):
        shutil.copy2(src_file, dst_file)
        print(f"Copied {filename} -> docs/wiki/")

# Also copy Home.md as README.md inside docs/wiki/ for easy browsing
shutil.copy2(os.path.join(src_dir, "Home.md"), os.path.join(dst_dir, "README.md"))
print("Created docs/wiki/README.md")
