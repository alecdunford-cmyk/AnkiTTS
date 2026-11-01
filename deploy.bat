@echo off
rem Refresh the add-on's runtime folders inside C:\AnkiTTS\addon.
rem
rem Anki loads the add-on through the junction
rem   %APPDATA%\Anki2\addons21\AnkiTTS -> C:\AnkiTTS\addon
rem so there is nothing to copy into addons21. Inside the repository the
rem add-on runs C:\AnkiTTS\src directly; addon\src is only needed for a
rem packaged (non-repository) copy. This script:
rem   1. mirrors src into addon\src (packaging), and
rem   2. rebuilds addon\libs from addon\requirements-libs.txt for Python 3.13
rem      (Anki 26.5 bundles CPython 3.13.13), keeping the old folder in
rem      AnkiTTS_backup.
rem Close Anki first: Windows locks the .pyd files in addon\libs.

setlocal
set ROOT=%~dp0
set ADDON=%ROOT%addon

echo Mirroring src into addon\src ...
robocopy "%ROOT%src" "%ADDON%\src" /MIR /XD __pycache__ /NFL /NDL /NJH /NJS
if %ERRORLEVEL% GEQ 8 goto :fail

echo Rebuilding addon\libs ...
if exist "%ADDON%\libs.new" rmdir /S /Q "%ADDON%\libs.new"
py -3.13 -m pip install --no-user --disable-pip-version-check --target "%ADDON%\libs.new" -r "%ADDON%\requirements-libs.txt"
if errorlevel 1 goto :fail

if exist "%ADDON%\libs" (
    if not exist "%ROOT%AnkiTTS_backup" mkdir "%ROOT%AnkiTTS_backup"
    move "%ADDON%\libs" "%ROOT%AnkiTTS_backup\libs-%RANDOM%%RANDOM%" >nul
    if errorlevel 1 goto :fail
)
move "%ADDON%\libs.new" "%ADDON%\libs" >nul
if errorlevel 1 goto :fail

py -3.13 -I -c "import sys; sys.path[:] = [r'%ADDON%\libs'] + [p for p in sys.path if 'site-packages' not in p]; import edge_tts; print('edge_tts', edge_tts.__version__, 'imports from addon\\libs')"
if errorlevel 1 goto :fail

echo Done.
exit /b 0

:fail
echo Deployment FAILED.
exit /b 1
