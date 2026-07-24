@echo off
setlocal

set ROOT_ENV=..\ .env
set ROOT_ENV=%ROOT_ENV: =%
if exist "%ROOT_ENV%" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT_ENV%") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if "%PAYPAY_MERCHANT_ID%"=="" (
  echo PAYPAY_MERCHANT_ID is missing. Add it to ..\.env or .env.
  exit /b 1
)
if "%PAYPAY_API_KEY%"=="" (
  echo PAYPAY_API_KEY is missing. Add it to ..\.env or .env.
  exit /b 1
)
if "%PAYPAY_API_SECRET%"=="" (
  echo PAYPAY_API_SECRET is missing. Add it to ..\.env or .env.
  exit /b 1
)

mvn spring-boot:run
