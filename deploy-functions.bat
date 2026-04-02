@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Deploy Azure Functions code only (zip + config-zip upload).
REM Usage:
REM   deploy-functions.bat [function_app_name] [resource_group]

cd /d "%~dp0"

set "FUNCTION_APP=%~1"
set "RESOURCE_GROUP=%~2"
set "ZIP_PATH=%TEMP%\capstone-functions-%RANDOM%.zip"

echo Starting Functions-only deployment...

where az >nul 2>nul
if errorlevel 1 (
  echo ERROR: Azure CLI not found. Please install it first.
  exit /b 1
)

call az account show >nul 2>nul
if errorlevel 1 (
  echo Not logged in to Azure. Logging in...
  call az login
  if errorlevel 1 (
    echo ERROR: Azure login failed.
    exit /b 1
  )
)

if not defined FUNCTION_APP (
  if exist "terraform\terraform.tfstate" (
    for /f "delims=" %%i in ('cd terraform ^&^& terraform output -raw function_app_name 2^>nul') do set "FUNCTION_APP=%%i"
  )
)

if not defined RESOURCE_GROUP (
  if exist "terraform\terraform.tfstate" (
    for /f "delims=" %%i in ('cd terraform ^&^& terraform output -raw resource_group_name 2^>nul') do set "RESOURCE_GROUP=%%i"
  )
)

if not defined FUNCTION_APP (
  echo ERROR: Function app name not found.
  echo Provide it as the first argument or ensure terraform outputs are available.
  echo Example: deploy-functions.bat my-function-app my-resource-group
  exit /b 1
)

if not defined RESOURCE_GROUP (
  echo ERROR: Resource group name not found.
  echo Provide it as the second argument or ensure terraform outputs are available.
  echo Example: deploy-functions.bat my-function-app my-resource-group
  exit /b 1
)

echo Function App : %FUNCTION_APP%
echo Resource Group: %RESOURCE_GROUP%

echo Enabling remote build settings for Python dependencies...
call az functionapp config appsettings set --name "%FUNCTION_APP%" --resource-group "%RESOURCE_GROUP%" --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true ENABLE_ORYX_BUILD=true >nul
if errorlevel 1 (
  echo ERROR: Failed to set remote build app settings.
  exit /b 1
)

set "PY311_EXE="
set "SKIP_FUNC_PUBLISH=0"
for /f "usebackq delims=" %%i in (`py -3.11 -c "import sys; print(sys.executable)" 2^>nul`) do set "PY311_EXE=%%i"
if defined PY311_EXE (
  for %%d in ("%PY311_EXE%") do set "PY311_DIR=%%~dpd"
  if defined PY311_DIR (
    set "PATH=%PY311_DIR%;%PATH%"
    set "PY_PYTHON=3.11"
    set "PY_PYTHON3=3.11"
    echo Using local Python 3.11 for publish: %PY311_EXE%
  )
) else (
  echo Python 3.11 not found locally.
  echo Skipping func publish and using zip deploy with remote build.
  set "SKIP_FUNC_PUBLISH=1"
)

set "FUNC_CMD="
where func >nul 2>nul
if not errorlevel 1 set "FUNC_CMD=func"
if not defined FUNC_CMD (
  if exist "%APPDATA%\npm\func.cmd" set "FUNC_CMD=%APPDATA%\npm\func.cmd"
)

if defined FUNC_CMD if "%SKIP_FUNC_PUBLISH%"=="0" (
  echo Publishing Functions with Core Tools...
  pushd functions
  call "%FUNC_CMD%" azure functionapp publish "%FUNCTION_APP%" --python
  set "PUBLISH_EXIT=%ERRORLEVEL%"
  popd
  if "!PUBLISH_EXIT!"=="0" goto after_deploy

  echo func returned a non-zero exit code. Verifying deployment health...
  call az functionapp function show --name "%FUNCTION_APP%" --resource-group "%RESOURCE_GROUP%" --function-name getSensorData >nul 2>nul
  if not errorlevel 1 (
    echo Deployment verified. Function metadata is present.
    echo Skipping zip fallback.
    goto after_deploy
  )

  echo WARNING: func publish failed and function metadata not found. Falling back to zip deploy...
)

if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%" >nul 2>nul

echo Creating deployment zip from functions\ ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '.\functions\*' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 (
  echo ERROR: Failed to create zip package.
  exit /b 1
)

echo Uploading zip package to Azure Functions...
call az functionapp deployment source config-zip --name "%FUNCTION_APP%" --resource-group "%RESOURCE_GROUP%" --src "%ZIP_PATH%"
if errorlevel 1 (
  echo ERROR: Zip deployment failed.
  del /f /q "%ZIP_PATH%" >nul 2>nul
  exit /b 1
)

:after_deploy

echo Restarting Function App...
call az functionapp restart --name "%FUNCTION_APP%" --resource-group "%RESOURCE_GROUP%" >nul
if errorlevel 1 (
  echo WARNING: Failed to restart function app automatically.
)

echo Waiting for app to warm up...
timeout /t 12 /nobreak >nul

echo Verifying health endpoint...
call az functionapp function show --name "%FUNCTION_APP%" --resource-group "%RESOURCE_GROUP%" --function-name healthCheck >nul 2>nul
if errorlevel 1 (
  echo WARNING: Could not confirm healthCheck function metadata yet.
) else (
  call az functionapp function keys list --name "%FUNCTION_APP%" --resource-group "%RESOURCE_GROUP%" --function-name healthCheck --query "default" -o tsv > "%TEMP%\fn_health_key.txt" 2>nul
  set /p "HEALTH_KEY=" < "%TEMP%\fn_health_key.txt"
  if exist "%TEMP%\fn_health_key.txt" del /f /q "%TEMP%\fn_health_key.txt" >nul 2>nul
  if defined HEALTH_KEY (
    call az rest --method get --url "https://%FUNCTION_APP%.azurewebsites.net/api/health?code=%HEALTH_KEY%" >nul 2>nul
    if errorlevel 1 (
      echo WARNING: Health endpoint probe failed. Please check Function App logs.
    ) else (
      echo Health endpoint probe succeeded.
    )
  )
)

del /f /q "%ZIP_PATH%" >nul 2>nul

echo.
echo Functions-only deployment complete.
echo.
exit /b 0
