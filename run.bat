@echo off
echo ========================================
echo   SISTEMA DE CORREOS MASIVOS
echo ========================================
echo.

REM Verificar si existe el entorno virtual
if not exist "venv" (
    echo [1/3] Creando entorno virtual...
    python -m venv venv
    echo Entorno virtual creado.
) else (
    echo [1/3] Entorno virtual ya existe.
)

echo.
echo [2/3] Activando entorno e instalando dependencias...
call venv\Scripts\activate
pip install -r requirements.txt --quiet

echo.
echo [3/3] Iniciando servidor...
echo.
echo ========================================
echo   Dashboard disponible en:
echo   http://localhost:8000
echo ========================================
echo.
echo Presiona Ctrl+C para detener el servidor
echo.

cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
