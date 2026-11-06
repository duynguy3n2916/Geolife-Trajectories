from pathlib import Path
from collections import Counter

root = Path(__file__).resolve().parents[2] / "data" / "raw" / "geolife" / "Data"
files = list(root.glob("*/Trajectory/*.plt"))
print("Tổng số file:", len(files))

col_counts = Counter()
bad_files = []
blank_lines = 0

for f in files:
    with open(f, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    if len(lines) < 7:
        bad_files.append((str(f), "ít hơn 7 dòng"))
        continue
    for line in lines[6:]:
        if not line.strip():
            blank_lines += 1
            continue
        col_counts[len(line.strip().split(","))] += 1

print("Số cột theo từng dòng dữ liệu:", col_counts)
print("Dòng trống:", blank_lines)
print("File bất thường:", len(bad_files), bad_files[:10])