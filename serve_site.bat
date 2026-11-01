@echo off
cd /d "%~dp0"
echo Space Shooter site: http://localhost:8735
python -m http.server 8735 --directory site
