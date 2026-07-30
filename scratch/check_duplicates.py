import os
import re

from PIL import Image


def dhash(image, hash_size=8):
    image = image.convert('L').resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(image.getdata())
    diff = []
    for row in range(hash_size):
        for col in range(hash_size):
            pixel_left = image.getpixel((col, row))
            pixel_right = image.getpixel((col + 1, row))
            diff.append(pixel_left > pixel_right)
    return ''.join('1' if d else '0' for d in diff)

def hamming_distance(s1, s2):
    return sum(c1 != c2 for c1, c2 in zip(s1, s2))

readme_path = r'v:\___VAC\__K\__CODE\_PY\_FastPrompter\README.md'
with open(readme_path, encoding='utf-8') as f:
    content = f.read()

img_paths = re.findall(r'src="([^"]+)"', content)
img_paths = [p for p in img_paths if p.endswith('.png')]
img_paths.extend(re.findall(r'!\[.*?\]\((.*?\.png)\)', content))
img_paths = list(set(img_paths))
img_paths.sort()

hashes = {}
base_dir = r'v:\___VAC\__K\__CODE\_PY\_FastPrompter'
for rel_path in img_paths:
    path = os.path.join(base_dir, rel_path)
    try:
        with Image.open(path) as i:
            hashes[rel_path] = dhash(i)
    except Exception as e:
        print(f'Error reading {rel_path}: {e}')

duplicates = set()
for i in range(len(img_paths)):
    for j in range(i + 1, len(img_paths)):
        img1 = img_paths[i]
        img2 = img_paths[j]
        if img1 not in hashes or img2 not in hashes:
            continue
        if img1 in duplicates or img2 in duplicates:
            continue
        diff = hamming_distance(hashes[img1], hashes[img2])
        if diff <= 10:
            print(f'Duplicate found in README: {img2} is similar to {img1} (diff: {diff})')
            duplicates.add(img2)

if not duplicates:
    print('No duplicates found in README')
