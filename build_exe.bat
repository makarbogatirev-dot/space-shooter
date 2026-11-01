@echo off
cd /d "%~dp0space_shuter v1.0"
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --icon space_shuter.ico ^
  --name SpaceShooter ^
  --add-data "images;images" ^
  space_shuter.py
