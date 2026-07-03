@echo off
set SECRET_KEY=469a6dd51e1069ddf3420b75ce73f882592c723605be27f0aaf418b31ce6e9a7
set DB_PATH=E:\scanweb\scan+web_v1.3\scan_data.db
cd /d E:\scanweb\scan+web_v1.3
"E:\Program Files (x86)\python\python.exe" -m waitress --host=0.0.0.0 --port=5001 app:app