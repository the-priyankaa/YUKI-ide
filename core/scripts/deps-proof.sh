#!/usr/bin/env bash
# Proves stdedit imports nothing outside the standard library.
# Run: bash scripts/deps-proof.sh   (writes deps-proof.txt)
set -euo pipefail

OUT="deps-proof.txt"

echo "== stdedit dependency proof ==" > "$OUT"
echo "python: $(python3 --version)" >> "$OUT"
echo "" >> "$OUT"

echo "-- sys.path (no site-packages should be required) --" >> "$OUT"
python3 -c "import sys; [print(p) for p in sys.path]" >> "$OUT"
echo "" >> "$OUT"

echo "-- import trace for stdedit (every module) --" >> "$OUT"
PYTHONPATH=src python3 -c "
import sys, importlib, pkgutil

before = set(sys.modules)
import stdedit
mods = sorted(m.name for m in pkgutil.walk_packages(
    stdedit.__path__, 'stdedit.'))
assert len(mods) >= 30, mods
for m in mods:
    importlib.import_module(m)
after = set(sys.modules)

new_mods = sorted(after - before)

third_party = []
for name in new_mods:
    mod = sys.modules.get(name)
    f = getattr(mod, '__file__', None)
    if f and 'site-packages' in f:
        third_party.append((name, f))

print(f'stdedit modules imported: {len(mods)}')
print('Newly imported modules:')
for n in new_mods:
    print(' -', n)

print()
if third_party:
    print('THIRD-PARTY MODULES FOUND (should be empty):')
    for n, f in third_party:
        print(' -', n, f)
else:
    print('No site-packages modules imported. Clean.')
" >> "$OUT"

echo "" >> "$OUT"
echo "Proof written to $OUT"
cat "$OUT"