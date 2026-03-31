@echo off
setlocal EnableExtensions
REM Deploy script for Soil Sensing Robot infrastructure and application (Windows)

cd /d "%~dp0"

set "MODE=%~1"
set "SWA_CMD="

echo Starting deployment of Soil Sensing Robot...
echo Checking prerequisites...

where az >nul 2>nul
if errorlevel 1 (
    echo ERROR: Azure CLI not found. Please install it first.
    exit /b 1
)

where terraform >nul 2>nul
if errorlevel 1 (
    echo ERROR: Terraform not found. Please install it first.
    exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
    echo ERROR: Node.js not found. Please install it first.
    exit /b 1
)

echo All prerequisites found

echo Checking Azure Static Web Apps support...
call az staticwebapp upload --help >nul 2>nul
if not errorlevel 1 set "SWA_CMD=upload"

if not defined SWA_CMD (
    call az staticwebapp deploy --help >nul 2>nul
    if not errorlevel 1 set "SWA_CMD=deploy"
)

if defined SWA_CMD (
    echo Using az staticwebapp command: %SWA_CMD%
) else (
    echo WARNING: az staticwebapp upload/deploy unavailable. Static Web App deploy will be skipped.
)

echo Checking Azure login status...
call az account show >nul 2>nul
if errorlevel 1 (
    echo Not logged in to Azure. Logging in...
    call az login
    if errorlevel 1 (
        echo ERROR: Azure login failed.
        exit /b 1
    )
)

echo Logged in to Azure

if /I "%MODE%"=="frontend" goto frontend_only

cd terraform
if not exist "terraform.tfvars" (
    echo terraform.tfvars not found. Creating from example...
    copy terraform.tfvars.example terraform.tfvars >nul
    echo Please edit terraform.tfvars with your values and run this script again.
    exit /b 1
)

echo Initializing Terraform...
call terraform init
if errorlevel 1 exit /b 1

echo Validating Terraform configuration...
call terraform validate
if errorlevel 1 exit /b 1

echo Planning infrastructure deployment...
call terraform plan -out=tfplan
if errorlevel 1 exit /b 1

echo Deploying infrastructure (this may take 10-15 minutes)...
call terraform apply tfplan
if errorlevel 1 exit /b 1

echo Getting deployment outputs...
for /f "delims=" %%i in ('terraform output -raw function_app_name') do set "FUNCTION_APP=%%i"
for /f "delims=" %%i in ('terraform output -raw static_web_app_name') do set "STATIC_WEB_APP=%%i"
for /f "delims=" %%i in ('terraform output -raw resource_group_name') do set "RESOURCE_GROUP=%%i"
for /f "delims=" %%i in ('terraform output -raw cdn_endpoint_url') do set "CDN_URL=%%i"
for /f "delims=" %%i in ('terraform output -raw static_website_url') do set "STATIC_URL=%%i"
cd ..

echo Deploying web application to Static Web App...
call :deploy_swa
if errorlevel 1 exit /b 1

echo Deploying Azure Functions...
cd functions
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

where func >nul 2>nul
if errorlevel 1 (
    if exist "%APPDATA%\npm\func.cmd" (
        echo Using Functions Core Tools from %APPDATA%\npm\func.cmd
        call "%APPDATA%\npm\func.cmd" azure functionapp publish "%FUNCTION_APP%" --python
        if errorlevel 1 exit /b 1
    ) else (
        echo Functions Core Tools not found. Using zip deploy fallback...
        set "FN_ZIP=%TEMP%\soilrobot-functions.zip"
        if exist "%FN_ZIP%" del /f /q "%FN_ZIP%" >nul 2>nul
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path .\* -DestinationPath '%FN_ZIP%' -Force"
        if errorlevel 1 (
            echo ERROR: Failed to create function zip package.
            exit /b 1
        )
        call az functionapp deployment source config-zip --name "%FUNCTION_APP%" --resource-group "%RESOURCE_GROUP%" --src "%FN_ZIP%"
        if errorlevel 1 (
            echo ERROR: Azure CLI zip deployment failed.
            exit /b 1
        )
    )
) else (
    call func azure functionapp publish "%FUNCTION_APP%" --python
    if errorlevel 1 exit /b 1
)
cd ..

echo.
echo Deployment complete!
echo.
echo Your application is available at:
echo    Static Website: %STATIC_URL%
echo    CDN URL: %CDN_URL%
goto end

:frontend_only
echo Frontend-only deploy selected.
cd terraform
for /f "delims=" %%i in ('terraform output -raw static_web_app_name') do set "STATIC_WEB_APP=%%i"
for /f "delims=" %%i in ('terraform output -raw resource_group_name') do set "RESOURCE_GROUP=%%i"
cd ..
call :deploy_swa
if errorlevel 1 exit /b 1
echo Frontend-only deployment complete.

:end
echo.
exit /b 0

:deploy_swa
if not defined SWA_CMD (
    echo WARNING: Skipping Static Web App deployment because no supported az staticwebapp command is available.
    exit /b 0
)

if /I "%SWA_CMD%"=="upload" (
    call az staticwebapp upload --name "%STATIC_WEB_APP%" --resource-group "%RESOURCE_GROUP%" --source web-app
    if not errorlevel 1 exit /b 0

    rem If upload exists but fails, try deploy as a fallback.
    call az staticwebapp deploy --help >nul 2>nul
    if errorlevel 1 (
        echo ERROR: static web app upload failed and deploy fallback is unavailable.
        exit /b 1
    )
)

call az staticwebapp deploy --name "%STATIC_WEB_APP%" --resource-group "%RESOURCE_GROUP%" --source web-app
if errorlevel 1 (
    echo ERROR: static web app deployment failed.
    exit /b 1
)
exit /b 0
