@echo off
setlocal enabledelayedexpansion

set "VCVARS="
for %%d in (Community Professional Enterprise BuildTools) do (
    if exist "C:\Program Files\Microsoft Visual Studio\2022\%%d\VC\Auxiliary\Build\vcvarsall.bat" (
        set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\%%d\VC\Auxiliary\Build\vcvarsall.bat"
    )
    if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\%%d\VC\Auxiliary\Build\vcvarsall.bat" (
        set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\%%d\VC\Auxiliary\Build\vcvarsall.bat"
    )
)

if defined VCVARS (
    echo [build] Found: !VCVARS!
    call "!VCVARS!" x64
) else (
    echo [build] vcvarsall.bat not found, trying cl from PATH...
)

echo [build] Starting Nuitka build...
cd /d D:\WeChatMsg
python -m nuitka --standalone --onefile --jobs=2 --nofollow-import-to=sympy --module-parameter=torch-disable-jit=yes --noinclude-numba-mode=nofollow --windows-icon-from-ico=D:\WeChatMsg\app_icon.ico --include-data-files=D:\WeChatMsg\memoir\decrypt\version_list.json=memoir\decrypt\version_list.json --include-data-dir=D:\WeChatMsg\scribe\resources=scribe\resources --output-dir=D:\WeChatMsg\build_nuitka2 --onefile-no-compression --output-filename=ChatMemoir.exe D:\WeChatMsg\gui.py

if %ERRORLEVEL% EQU 0 (
    echo [build] SUCCESS
) else (
    echo [build] FAILED with error %ERRORLEVEL%
)
endlocal
