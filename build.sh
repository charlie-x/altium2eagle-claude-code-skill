set -e
export PYTHONIOENCODING=utf-8
python sch.py
python extract.py
python genbrd.py
python gensch.py
python emit.py
python check.py
