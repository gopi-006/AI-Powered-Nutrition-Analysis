@echo off
REM Nutrition Analyzer Flask Application Runner
echo Starting Nutrition Analyzer Flask Application...

REM Activate virtual environment
call "%~dp0..\..\.venv\Scripts\activate.bat"

REM Change to app directory
cd app

REM Run the Flask application
python app.py

REM Pause to see any error messages
pause