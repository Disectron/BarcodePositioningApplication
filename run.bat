@echo off
REM ===================================================================
REM  AOPS - Windows launcher.
REM
REM  Double-click this file, or run it from a terminal.
REM
REM  On the FIRST run it creates a .venv folder and installs the
REM  dependencies into it - that takes a few minutes and needs an
REM  internet connection. Every run after that starts immediately.
REM
REM  Pass arguments through for headless use:
REM      run.bat info
REM      run.bat export -o out
REM ===================================================================

setlocal

REM pushd rather than "cd /d": cmd.exe cannot hold a UNC path as its current
REM directory, so cd /d fails on \\server\share\AOPS and every relative path
REM below would then resolve against C:\Windows. pushd maps a temporary drive
REM letter instead, so a network-share checkout works unchanged.
pushd "%~dp0" || goto bad_path

set "VENV=.venv"
set "VPY=%VENV%\Scripts\python.exe"
REM Written only after a successful install. Its presence - not the mere
REM existence of the venv - is what marks setup as complete. "python -m venv"
REM creates python.exe BEFORE installing anything, so gating on the interpreter
REM would strand an interrupted install in a half-built venv forever.
set "STAMP=%VENV%\.aops-install-complete"

if not exist "%STAMP%" goto setup
"%VPY%" -c "" >nul 2>&1
if errorlevel 1 goto setup
goto launch


:setup
echo.
echo   First run - setting up. This happens once.
echo.

call :find_python
if errorlevel 1 goto no_python

REM Clear away any half-built environment from an interrupted earlier run.
if exist "%VENV%" rmdir /s /q "%VENV%" 2>nul

echo   Using %BASEPY%
echo   Creating virtual environment in %VENV% ...
%BASEPY% -m venv "%VENV%"
if errorlevel 1 goto venv_failed

echo   Installing dependencies, please wait ...
echo.
REM Unchecked on purpose: a failed self-upgrade is harmless, and the real
REM install on the next line is the authoritative success signal.
"%VPY%" -m pip install --upgrade pip --quiet
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto pip_failed

> "%STAMP%" echo ok

echo.
echo   Setup complete.
echo.


:launch
"%VPY%" run.py %*
REM Capture immediately - any intervening command would overwrite it.
REM "if errorlevel 1" is a signed >= test and so misses negative exit codes;
REM a native crash (0xC0000005 = -1073741819) would slip through as success
REM and the console would close with nothing to read.
set "RC=%errorlevel%"
if %RC% neq 0 goto run_failed
popd
endlocal
exit /b 0


REM --- Locate a Python 3.12+ interpreter -----------------------------
REM "if not errorlevel 1" inside the loop body reads the live exit code at
REM execution time, so no delayed expansion is needed; BASEPY is only read
REM after this subroutine returns.
:find_python
for %%C in ("py -3.13" "py -3.12" "py -3" "python" "python3") do (
    %%~C -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "BASEPY=%%~C"
        exit /b 0
    )
)
exit /b 1


REM --- Failure paths -------------------------------------------------
:bad_path
REM No popd here - pushd is what failed.
echo.
echo   Could not enter the project folder:
echo       %~dp0
echo.
echo   If the project is on a network share, copy it to a local drive
echo   such as C:\AOPS and run it from there.
echo.
pause
endlocal
exit /b 1

:no_python
echo.
echo   ======================================================================
echo     Python 3.12 or newer was not found
echo   ======================================================================
echo.
echo     Download it from:  https://www.python.org/downloads/
echo.
echo     IMPORTANT: during installation, tick
echo         "Add python.exe to PATH"
echo.
echo     Then close this window and run this file again.
echo.
pause
popd
endlocal
exit /b 1

:venv_failed
echo.
echo   Could not create the virtual environment.
echo.
echo   If this folder is inside OneDrive or a synced folder, try copying
echo   the project somewhere local first, for example C:\AOPS
echo.
pause
popd
endlocal
exit /b 1

:pip_failed
echo.
echo   Dependency installation failed.
echo.
echo   Check your internet connection and run this file again - setup will
echo   start over from scratch. If you are behind a corporate proxy or
echo   firewall, pip may need to be configured for it.
echo.
pause
popd
endlocal
exit /b 1

:run_failed
echo.
echo   AOPS exited with an error. The message above explains why.
echo.
pause
popd
REM Single line: endlocal would otherwise discard RC before exit is parsed.
endlocal & exit /b %RC%
