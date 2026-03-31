@echo off
REM Deploy script for Soil Sensing Robot infrastructure and application (Windows)
REM This script deploys the complete solution to Azure

set MODE=%1
if /I "%MODE%"=="frontend" goto frontend_only

echo Starting deployment of Soil Sensing Robot...

REM Check prerequisites
echo Checking prerequisites...

where az >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Azure CLI not found. Please install it first.
    exit /b 1
)

where terraform >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Terraform not found. Please install it first.
    exit /b 1
)

where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Node.js not found. Please install it first.
    exit /b 1
)

echo All prerequisites found

REM Check Azure login
echo Checking Azure login status...
call az account show >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Not logged in to Azure. Logging in...
    call az login
)

echo Logged in to Azure

REM Navigate to terraform directory
cd terraform

REM Check if terraform.tfvars exists
if not exist "terraform.tfvars" (
    echo terraform.tfvars not found. Creating from example...
    copy terraform.tfvars.example terraform.tfvars
    echo Please edit terraform.tfvars with your values and run this script again.
    exit /b 1
)

REM Initialize Terraform
echo Initializing Terraform...
call terraform init

REM Validate configuration
echo Validating Terraform configuration...
call terraform validate

REM Plan deployment
echo Planning infrastructure deployment...
call terraform plan -out=tfplan

REM Apply Terraform
echo Deploying infrastructure (this may take 10-15 minutes)...
call terraform apply tfplan

REM Get outputs
echo Getting deployment outputs...
for /f "delims=" %%i in ('terraform output -raw function_app_name') do set FUNCTION_APP=%%i
for /f "delims=" %%i in ('terraform output -raw static_web_app_name') do set STATIC_WEB_APP=%%i
for /f "delims=" %%i in ('terraform output -raw resource_group_name') do set RESOURCE_GROUP=%%i
for /f "delims=" %%i in ('terraform output -raw cdn_endpoint_url') do set CDN_URL=%%i
for /f "delims=" %%i in ('terraform output -raw static_website_url') do set STATIC_URL=%%i

cd ..

REM Deploy Web Application
echo Deploying web application to Static Web App...
call az staticwebapp upload ^
    --name "%STATIC_WEB_APP%" ^
    --resource-group "%RESOURCE_GROUP%" ^
    --source web-app

echo Web application deployed to Static Web App

if /I "%MODE%"=="frontend" goto done

REM Deploy Azure Functions
echo Deploying Azure Functions...
cd functions
REM For Python apps, we use pip instead of npm
python -m pip install -r requirements.txt
call func azure functionapp publish "%FUNCTION_APP%" --python

cd ..

echo.
echo Deployment complete!
echo.
echo Your application is available at:
echo    Static Website: %STATIC_URL%
echo    CDN URL: %CDN_URL%
echo.
echo Next steps:
echo    1. Open the CDN URL in your browser
echo    2. Configure your microcontroller to connect to WiFi
echo    3. Enter the microcontroller IP address in the web interface
echo    4. Monitor sensor data in real-time

goto end

:frontend_only
REM Frontend-only deployment path
echo Frontend-only deploy: using Static Web App upload
cd terraform
for /f "delims=" %%i in ('terraform output -raw static_web_app_name') do set STATIC_WEB_APP=%%i
for /f "delims=" %%i in ('terraform output -raw resource_group_name') do set RESOURCE_GROUP=%%i
cd ..
call az staticwebapp upload ^
    --name "%STATIC_WEB_APP%" ^
    --resource-group "%RESOURCE_GROUP%" ^
    --source web-app

echo Frontend-only deployment complete.

goto done

:done

echo.
echo Deployment complete!
echo.

goto end

:end
echo.
