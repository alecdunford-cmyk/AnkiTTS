@echo off
echo.
echo =====================================
echo Deploying AnkiTTS...
echo =====================================
echo.

set SOURCE=C:\AnkiTTS
set DEST=C:\Users\alecd\AppData\Roaming\Anki2\addons21\AnkiTTS

robocopy "%SOURCE%\addon" "%DEST%" /E
robocopy "%SOURCE%\src" "%DEST%\src" /E
robocopy "%SOURCE%\addon\libs" "%DEST%\libs" /E

copy "%SOURCE%\config.json" "%DEST%" >nul

echo.
echo =====================================
echo Deployment complete!
echo =====================================
pause