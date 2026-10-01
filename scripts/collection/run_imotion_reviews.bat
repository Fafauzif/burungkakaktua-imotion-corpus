@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "SCRIPT=%~dp0scrape_imotion_reviews.py"
set "REQ=%~dp0requirements.txt"
set "INPUT=%~dp0ID App for IMOTION.xlsx"
set "DEPS_MARKER=%~dp0.venv\.imotion_deps_ready"

rem Double-clicking (no arguments) opens the low-effort numbered menu.
if "%~1"=="" goto :menu
if /I "%~1"=="menu" goto :menu
if /I "%~1"=="help" goto :help
if /I "%~1"=="install" goto :install_only
if /I "%~1"=="run" goto :run_named
if /I "%~1"=="clean" goto :clean
if /I "%~1"=="retry" goto :retry
if /I "%~1"=="refresh" goto :refresh
if /I "%~1"=="plan" goto :plan
goto :run

:ensure_install
if exist "%DEPS_MARKER%" if exist "%PYTHON_EXE%" exit /b 0
if exist "%DEPS_MARKER%" del /q "%DEPS_MARKER%" >nul 2>nul
if not exist "%PYTHON_EXE%" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv "%~dp0.venv"
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 (
            python -m venv "%~dp0.venv"
        ) else (
            where winget >nul 2>nul
            if errorlevel 1 (
                echo Python 3 was not found and winget is unavailable. Install Python 3.10+ and rerun this file.
                exit /b 1
            )
            echo Python 3 was not found. Installing Python 3.12 with winget...
            winget install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements
            if errorlevel 1 exit /b 1
            if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
                "%LocalAppData%\Programs\Python\Python312\python.exe" -m venv "%~dp0.venv"
            ) else (
                echo Python was installed but is not visible in this session. Reopen Command Prompt and run this file again.
                exit /b 1
            )
        )
    )
    if errorlevel 1 exit /b 1
)
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" -m pip install -r "%REQ%"
if errorlevel 1 exit /b 1
>"%DEPS_MARKER%" echo ready
exit /b 0

:install_only
rem Explicit install means check/update packages even if the marker exists.
if exist "%DEPS_MARKER%" del /q "%DEPS_MARKER%" >nul 2>nul
call :ensure_install
if errorlevel 1 goto :fail
echo Dependencies installed in .venv.
goto :done

:run
call :ensure_install
if errorlevel 1 goto :fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" %*
if errorlevel 1 goto :fail
goto :done

:run_named
call :ensure_install
if errorlevel 1 goto :fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" %~2 %~3 %~4 %~5 %~6 %~7 %~8 %~9
if errorlevel 1 goto :fail
goto :done

:clean
call :ensure_install
if errorlevel 1 goto :fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --clean-only %~2 %~3 %~4 %~5 %~6 %~7 %~8 %~9
if errorlevel 1 goto :fail
goto :done

:retry
call :ensure_install
if errorlevel 1 goto :fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --retry-failed --refresh --google-locales "id:id,en:us" --apple-country us %~2 %~3 %~4 %~5 %~6 %~7 %~8 %~9
if errorlevel 1 goto :fail
goto :done

:refresh
call :ensure_install
if errorlevel 1 goto :fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --refresh %~2 %~3 %~4 %~5 %~6 %~7 %~8 %~9
if errorlevel 1 goto :fail
goto :done

:plan
call :ensure_install
if errorlevel 1 goto :fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --plan %~2 %~3 %~4 %~5 %~6 %~7 %~8 %~9
if errorlevel 1 goto :fail
goto :done

:menu
:menu_loop
cls
echo ================================================================
echo              IMOTION REVIEW SCRAPER
echo ================================================================
echo Choose an option by typing its number.
echo.
echo   1. Install or update dependencies
echo   2. Full scrape (resume saved progress)
echo   3. Retry failed or empty jobs
echo   4. Refresh completed jobs for new reviews
echo   5. Rebuild cleaned CSVs only
echo   6. Show apps and store IDs (no network)
echo   7. Open output reports folder
echo   8. Exit
echo.
choice /C 12345678 /N /M "Your choice [1-8]: "
if errorlevel 8 goto :done
if errorlevel 7 goto :menu_reports
if errorlevel 6 goto :menu_plan
if errorlevel 5 goto :menu_clean
if errorlevel 4 goto :menu_refresh
if errorlevel 3 goto :menu_retry
if errorlevel 2 goto :menu_full
if errorlevel 1 goto :menu_install
goto :menu_loop

:menu_install
if exist "%DEPS_MARKER%" del /q "%DEPS_MARKER%" >nul 2>nul
call :ensure_install
set "MENU_RC=%ERRORLEVEL%"
if not "%MENU_RC%"=="0" goto :menu_pause_fail
echo Dependencies installed in .venv.
goto :menu_pause

:menu_full
call :configure_run "Full scrape"
if errorlevel 1 goto :menu_loop
call :run_configured
set "MENU_RC=%ERRORLEVEL%"
goto :menu_pause_result

:menu_retry
call :configure_run "Retry failed/empty jobs"
if errorlevel 1 goto :menu_loop
call :retry_configured
set "MENU_RC=%ERRORLEVEL%"
goto :menu_pause_result

:menu_refresh
call :configure_run "Refresh completed jobs"
if errorlevel 1 goto :menu_loop
call :refresh_configured
set "MENU_RC=%ERRORLEVEL%"
goto :menu_pause_result

:menu_clean
call :ensure_install
if errorlevel 1 goto :menu_pause_fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --clean-only
set "MENU_RC=%ERRORLEVEL%"
goto :menu_pause_result

:menu_plan
call :ensure_install
if errorlevel 1 goto :menu_pause_fail
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --plan
set "MENU_RC=%ERRORLEVEL%"
goto :menu_pause_result

:menu_reports
if not exist "%~dp0output\reports" (
    echo No reports folder exists yet. Run a scrape first.
    goto :menu_pause
)
start "IMOTION reports" explorer.exe "%~dp0output\reports"
echo Opened output\reports in File Explorer.
goto :menu_pause

rem ----------------------- menu configuration -----------------------
:configure_run
set "MENU_TITLE=%~1"
set "MENU_WORKERS=8"
set "MENU_RETRIES=5"
set "MENU_WAIT=2"
set "MENU_LOCALES=id:id"
if /I "%MENU_TITLE%"=="Retry failed/empty jobs" set "MENU_LOCALES=id:id,en:us"
set "MENU_APPLE_COUNTRY=id"
if /I "%MENU_TITLE%"=="Retry failed/empty jobs" set "MENU_APPLE_COUNTRY=us"
set "MENU_MAX_PAGES=0"
echo.
echo %MENU_TITLE% settings (press a number at each prompt).
echo.
choice /C 1234 /N /M "Workers: 1=8 (recommended), 2=12, 3=16, 4=custom [1-4]: "
set "MENU_CHOICE=%errorlevel%"
if "%MENU_CHOICE%"=="4" set /p "MENU_WORKERS=Enter workers (1-32): "
if "%MENU_CHOICE%"=="3" set "MENU_WORKERS=16"
if "%MENU_CHOICE%"=="2" set "MENU_WORKERS=12"
if "%MENU_CHOICE%"=="1" set "MENU_WORKERS=8"
choice /C 1234 /N /M "Retries: 1=5 (recommended), 2=8, 3=12, 4=custom [1-4]: "
set "MENU_CHOICE=%errorlevel%"
if "%MENU_CHOICE%"=="4" set /p "MENU_RETRIES=Enter retries (1-20): "
if "%MENU_CHOICE%"=="3" set "MENU_RETRIES=12"
if "%MENU_CHOICE%"=="2" set "MENU_RETRIES=8"
if "%MENU_CHOICE%"=="1" set "MENU_RETRIES=5"
choice /C 123 /N /M "Google locales: 1=id only (fast), 2=id + en-US (fallback), 3=custom [1-3]: "
set "MENU_CHOICE=%errorlevel%"
if "%MENU_CHOICE%"=="3" set /p "MENU_LOCALES=Enter locales like id:id,en:us: "
if "%MENU_CHOICE%"=="2" set "MENU_LOCALES=id:id,en:us"
if "%MENU_CHOICE%"=="1" set "MENU_LOCALES=id:id"
choice /C 123 /N /M "Apple storefront: 1=id, 2=us (retry fallback), 3=custom [1-3]: "
set "MENU_CHOICE=%errorlevel%"
if "%MENU_CHOICE%"=="3" set /p "MENU_APPLE_COUNTRY=Enter Apple storefront country (e.g. id or us): "
if "%MENU_CHOICE%"=="2" set "MENU_APPLE_COUNTRY=us"
if "%MENU_CHOICE%"=="1" set "MENU_APPLE_COUNTRY=id"
choice /C 123 /N /M "Page limit: 1=all (recommended), 2=first page (test), 3=custom [1-3]: "
set "MENU_CHOICE=%errorlevel%"
if "%MENU_CHOICE%"=="3" set /p "MENU_MAX_PAGES=Enter max pages (0=all): "
if "%MENU_CHOICE%"=="2" set "MENU_MAX_PAGES=1"
if "%MENU_CHOICE%"=="1" set "MENU_MAX_PAGES=0"
echo.
echo Using workers=!MENU_WORKERS!, retries=!MENU_RETRIES!, wait=!MENU_WAIT!s, Google locales=!MENU_LOCALES!, Apple country=!MENU_APPLE_COUNTRY!, max-pages=!MENU_MAX_PAGES!.
exit /b 0

:run_configured
call :ensure_install
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --workers "%MENU_WORKERS%" --retries "%MENU_RETRIES%" --retry-wait "%MENU_WAIT%" --google-locales "%MENU_LOCALES%" --apple-country "%MENU_APPLE_COUNTRY%" --max-pages "%MENU_MAX_PAGES%"
exit /b %errorlevel%

:retry_configured
call :ensure_install
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --retry-failed --refresh --workers "%MENU_WORKERS%" --retries "%MENU_RETRIES%" --retry-wait "%MENU_WAIT%" --google-locales "%MENU_LOCALES%" --apple-country "%MENU_APPLE_COUNTRY%" --max-pages "%MENU_MAX_PAGES%"
exit /b %errorlevel%

:refresh_configured
call :ensure_install
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" "%SCRIPT%" --input "%INPUT%" --refresh --workers "%MENU_WORKERS%" --retries "%MENU_RETRIES%" --retry-wait "%MENU_WAIT%" --google-locales "%MENU_LOCALES%" --apple-country "%MENU_APPLE_COUNTRY%" --max-pages "%MENU_MAX_PAGES%"
exit /b %errorlevel%

:menu_pause_result
if not "%MENU_RC%"=="0" goto :menu_pause_fail
echo.
echo Finished. Read output\reports\cleaning_summary.md for the cleaning summary.
goto :menu_pause

:menu_pause_fail
echo.
echo The run ended with an error. Read output\logs\ and output\reports\cleaning_summary.md.

:menu_pause
echo.
pause
goto :menu_loop

:help
echo.
echo IMOTION review scraper
echo.
echo Double-click this file (or run it with no arguments) for the numbered menu.
echo.
echo   run_imotion_reviews.bat plan            Check apps/jobs without contacting stores
echo   run_imotion_reviews.bat retry           Retry failed/empty jobs
echo   run_imotion_reviews.bat refresh         Re-scrape jobs marked successful
echo   run_imotion_reviews.bat clean           Rebuild CSVs from saved raw JSONL
echo   run_imotion_reviews.bat install         Install or update the local Python environment
echo.
echo Examples:
echo   run_imotion_reviews.bat --workers 8 --google-locales id:id,en:us
echo   run_imotion_reviews.bat retry --retries 8 --retry-wait 3
echo   run_imotion_reviews.bat refresh --max-pages 0
goto :done

:fail
echo.
echo The run ended with an error. Read output\logs\ and output\reports\cleaning_summary.md.
exit /b 1

:done
exit /b 0
