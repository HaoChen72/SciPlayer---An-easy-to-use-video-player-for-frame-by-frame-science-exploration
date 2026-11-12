#!/bin/bash
# Builds the Windows 11 x64 installer of SciPlayer on Linux:
#   1. a private Python 3.12 for win-64 (conda-forge, through py-rattler), with PyAV on an LGPL-only
#      FFmpeg (conda-forge's lgpl build: no GPL parts such as x264 / x265), NumPy (OpenBLAS) and Pillow
#   2. the win_amd64 wheels: PySide6 (Qt), pyqtgraph, tifffile, scipy, h5py, sounddevice
#   3. prune what SciPlayer does not use
#   4. SciPlayer.exe launcher (MinGW-w64, with the icon, version and manifest)
#   5. the installer (NSIS): dist/SciPlayer-<version>-Setup-x64.exe
# Needs: python3 (with py-rattler and pefile in $VENV), x86_64-w64-mingw32-gcc / windres, makensis.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(grep -oP "APP_VERSION = '\K[^']+" "$HERE/app/sciplayer.py")"
WORK="${WORK:-$HERE/_build}"
VENV="${VENV:-$HERE/.venv}"                 # a Python with py-rattler and pip
mkdir -p "$WORK" "$HERE/dist"
echo "SciPlayer $VERSION -> $WORK"

# ---- 1. Python for win-64 ---------------------------------------------------------------
# PyAV from conda-forge on its LGPL FFmpeg build: the PyPI wheel of PyAV bundles x264 and x265 (GPL), and a
# GPL part would make the whole program GPL, which SciPlayer's non-commercial licence cannot be
CONDA_SPECS='python 3.12.*|av ==19.0.2|ffmpeg * *lgpl*|numpy ==1.26.4|libblas * *openblas|pillow'
if [ ! -f "$WORK/pyenv/python312.dll" ] || [ "$(cat "$WORK/pyenv/.specs" 2>/dev/null)" != "$CONDA_SPECS" ]; then
  rm -rf "$WORK/pyenv"
  "$VENV/bin/python" - "$WORK/pyenv" "$CONDA_SPECS" <<'EOF'
import asyncio, sys, rattler
from rattler import solve, install, Platform
async def main():
    recs = await solve(sources=["conda-forge"], specs=sys.argv[2].split('|'), platforms=[Platform("win-64"), Platform("noarch")])
    await install(recs, target_prefix=sys.argv[1], platform=Platform("win-64"), execute_link_scripts=False)
asyncio.run(main())
EOF
  echo "$CONDA_SPECS" > "$WORK/pyenv/.specs"
fi
# the licences of what conda brought: listed in LICENSES.txt, and no GPL part allowed (only LGPL and permissive)
"$VENV/bin/python" - "$WORK/pyenv" "$WORK/conda_licenses.txt" <<'EOF'
import json, glob, os, re, sys
rows = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], 'conda-meta', '*.json'))):
    m = json.load(open(f))
    rows.append((m['name'], m['version'], m.get('license') or '?'))
def gpl_only(lic):                 # every alternative of the licence is GPL (FreeType: "GPL-2.0-only OR FTL" is fine)
    return all(re.search(r'(?<!L)GPL', alt) and not re.search(r'exception', alt, re.I) for alt in re.split(r'\s+OR\s+', lic))
bad = [r for r in rows if gpl_only(r[2])]
open(sys.argv[2], 'w').write(''.join('  %-28s %-26s %s\n' % r for r in rows))
if bad:
    sys.exit('GPL components in the runtime: %s' % bad)
EOF

# ---- 2. wheels ------------------------------------------------------------------------------
# numpy 1.26 and Qt 6.10: newer ones do not start under Wine 9, where this build is tested
# (numpy 2 and h5py 3.13+ hang on import; Qt 6.12 calls a colour-management function Wine lacks)
rm -rf "$WORK/rt" && cp -a "$WORK/pyenv" "$WORK/rt"
# (no dependencies pulled: NumPy, Pillow and PyAV come from conda-forge above)
"$VENV/bin/pip" install -q --upgrade --no-deps --target "$WORK/rt/Lib/site-packages" --platform win_amd64 --python-version 3.12 \
  --implementation cp --abi cp312 --only-binary=:all: \
  "pyside6-essentials==6.10.2" "shiboken6==6.10.2" "pyqtgraph==0.14.0" "tifffile==2026.3.3" "scipy==1.15.3" "h5py==3.12.1" \
  "sounddevice==0.5.6" "cffi==2.1.1" "pycparser==3.12" "colorama==0.4.6"

# ---- 3. prune -------------------------------------------------------------------------------
cd "$WORK/rt"
S=Lib/site-packages; P=$S/PySide6
rm -rf conda-meta CACHEDIR.TAG Scripts Tools include libs Lib/test Lib/idlelib Lib/tkinter Lib/turtledemo Lib/ensurepip \
       Lib/lib2to3 Lib/pydoc_data Lib/venv Library/lib Library/include Library/share $S/bin $S/*.whl $S/README.txt
rm -f Library/bin/tcl*.dll Library/bin/tk*.dll Library/bin/*.exe DLLs/_tkinter.pyd
( cd $P && ls | grep -v -E '^(Qt6(Core|Gui|Widgets|OpenGL|OpenGLWidgets|Svg|SvgWidgets|PrintSupport|Network)\.dll|Qt(Core|Gui|Widgets|OpenGL|OpenGLWidgets|Svg|SvgWidgets|PrintSupport|Network)\.pyd|__init__\.py|_config\.py|_git_pyside_version\.py|pyside6\.abi3\.dll|msvcp140.*\.dll|vcruntime140.*\.dll|concrt140\.dll|plugins|support|scripts)$' | xargs rm -rf )
( cd $P/plugins && ls | grep -v -E '^(platforms|styles|imageformats|iconengines)$' | xargs rm -rf; rm -f imageformats/qpdf.dll platforms/qminimal.dll )
find . -type d \( -name tests -o -name test -o -name __pycache__ \) -prune -exec rm -rf {} +
find . \( -name "*.pyi" -o -name "*.pdb" -o -name "*.lib" \) -delete
# conda's library folder: only the DLLs something here loads (FFmpeg's filters and devices bring fonts,
# SDL, Vulkan, ... not all needed), followed through the import tables from Python and every module
"$VENV/bin/python" - . <<'EOF'
import os, re, subprocess, sys
root = os.path.abspath(sys.argv[1])
lib = os.path.join(root, 'Library', 'bin')
have = {f.lower(): os.path.join(lib, f) for f in os.listdir(lib) if f.lower().endswith('.dll')}
def imports(path):
    out = subprocess.run(['x86_64-w64-mingw32-objdump', '-p', path], capture_output=True, text=True).stdout
    return {m.lower() for m in re.findall(r'DLL Name: (\S+)', out)}
start = []
for d, _, fs in os.walk(root):
    if os.path.abspath(d) == lib:
        continue
    start += [os.path.join(d, f) for f in fs if f.lower().endswith(('.pyd', '.dll'))]
# Windows' own ICU (System32\icuuc.dll, icuin.dll, icu.dll): Qt imports it from there. conda's ICU under the
# same name must not be kept, as Library\bin is searched before System32 and Qt would get it and not load
# (its functions carry a version suffix: ucnv_open_78, not ucnv_open). conda's own users take icuuc78.dll.
windows_own = {'icu.dll', 'icuuc.dll', 'icuin.dll'}
def named(path):                  # DLLs it names otherwise: export forwarders ("libopenblas.cblas_sdot", as
    data = open(path, 'rb').read().lower()       # in conda's libcblas) and names it loads at run time
    return {f for f in have if f.encode() in data or (f[:-4] + '.').encode() in data}
need, todo = set(), list(start)
while todo:
    p = todo.pop()
    deps = imports(p) | (named(p) if os.path.dirname(os.path.abspath(p)) == lib else set())
    for dep in deps - windows_own:
        if dep in have and dep not in need:
            need.add(dep)
            todo.append(have[dep])
keep = ('api-ms-', 'ucrtbase', 'vcruntime', 'msvcp', 'concrt', 'vcomp')
gone = [f for f in have if f not in need and not f.startswith(keep)]
for f in gone:
    os.remove(have[f])
print('Library/bin: %d DLLs kept, %d that nothing loads removed' % (len(have) - len(gone), len(gone)))
EOF
# every function each module imports must be in the DLL Windows gives it: its own folder's copy, or a copy in
# the folders searched before System32 (runtime\, Library\bin\; a DLL already loaded by name is shared).
# Wine supplies its own C++ runtime and ICU, so a mismatch here does not show up in tests under Wine.
"$VENV/bin/python" - . <<'EOF'
import os, sys, collections, pefile
pefile.MAX_IMPORT_SYMBOLS = 1 << 20                     # (Qt's tables are large)
root = os.path.abspath(sys.argv[1])
copies = collections.defaultdict(list)
for d, _, fs in os.walk(root):
    for f in fs:
        if f.lower().endswith(('.dll', '.pyd')):
            copies[f.lower()].append(os.path.join(d, f))
shared = {os.path.normcase(root), os.path.normcase(os.path.join(root, 'Library', 'bin'))}
exp = {}
def exports(p):
    if p not in exp:
        pe = pefile.PE(p, fast_load=True, max_symbol_exports=1 << 20)
        pe.parse_data_directories([pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
        exp[p] = {s.name for s in pe.DIRECTORY_ENTRY_EXPORT.symbols if s.name} if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT') else set()
    return exp[p]
bad = []
for name, ps in copies.items():
    for p in ps:
        pe = pefile.PE(p, fast_load=True)
        pe.parse_data_directories([pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        for e in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
            dep = e.dll.decode().lower()
            want = {i.name for i in e.imports if i.name}
            for c in copies.get(dep, []):
                if os.path.dirname(c) == os.path.dirname(p) or os.path.normcase(os.path.dirname(c)) in shared:
                    miss = want - exports(c)
                    if miss:
                        bad.append('%s needs %d functions that %s lacks, e.g. %s'
                                   % (os.path.relpath(p, root), len(miss), os.path.relpath(c, root), sorted(miss)[0].decode()))
if bad:
    sys.exit('DLLs that would not load on Windows:\n  ' + '\n  '.join(bad))
print('imports: every module finds its functions')
EOF

# ---- 4. launcher ----------------------------------------------------------------------------
cd "$HERE/launcher"
sed -e "s/1,0,0,0/${VERSION//./,},0/g" -e "s/\"1.0.0\"/\"$VERSION\"/g" res.rc > "$WORK/res.rc"
sed -i "s#\"../assets/#\"$HERE/assets/#; s#\"app.manifest\"#\"$HERE/launcher/app.manifest\"#" "$WORK/res.rc"
x86_64-w64-mingw32-windres "$WORK/res.rc" -O coff -o "$WORK/res.o"
x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -static -o "$WORK/SciPlayer.exe" launcher.c "$WORK/res.o" -lshell32

# ---- stage: the installation folder ------------------------------------------------------------
rm -rf "$WORK/stage" && mkdir -p "$WORK/stage/app"
cp "$WORK/SciPlayer.exe" "$WORK/stage/"
cp -a "$WORK/rt" "$WORK/stage/runtime"
cp "$HERE"/app/sciplayer*.py "$HERE/assets/sciplayer.ico" "$HERE/assets/sciplayer_256.png" "$WORK/stage/app/"
cp "$HERE/LICENSES.txt" "$WORK/stage/" 2>/dev/null || true
# SciPlayer's own licence (the repository's LICENSE.md), shown by the installer and kept beside the program
sed 's/$/\r/' "$HERE/../LICENSE.md" > "$WORK/stage/LICENSE.txt"
{ echo; echo "Packages of the private Python (conda-forge: runtime\\), with their licences:"; cat "$WORK/conda_licenses.txt"; } >> "$WORK/stage/LICENSES.txt"

# byte-compile with the Windows Python itself (unchecked hashes: valid wherever it is installed)
if [ "${PRECOMPILE:-1}" = 1 ] && command -v wine >/dev/null; then
  export WINEDEBUG=-all WINEPREFIX="${WINEPREFIX:-$HOME/.wine-sciplayer}"
  ( cd "$WORK/stage" && timeout 900 xvfb-run -a wine cmd /c \
      "runtime\\python.exe -s -m compileall -q -j 0 --invalidation-mode unchecked-hash runtime\\Lib app > compile.log 2>&1" >/dev/null 2>&1 || true )
  rm -f "$WORK/stage/compile.log"
fi

# ---- 5. installer ---------------------------------------------------------------------------
makensis -V2 -DVERSION="$VERSION" -DSTAGE="$WORK/stage" -DASSETS="$HERE/assets" -DOUTFILE="$HERE/dist/SciPlayer-$VERSION-Setup-x64.exe" \
  "$HERE/installer/sciplayer.nsi"
ls -la "$HERE/dist"
