#!/bin/bash
echo "========================================"
echo "   SISTEMA DE CORREOS MASIVOS"
echo "========================================"
echo ""

# Verificar si existe el entorno virtual
if [ ! -d "venv" ]; then
    echo "[1/3] Creando entorno virtual..."
    python3 -m venv venv
    echo "Entorno virtual creado."
else
    echo "[1/3] Entorno virtual ya existe."
fi

echo ""
echo "[2/3] Activando entorno e instalando dependencias..."
source venv/bin/activate
pip install -r requirements.txt --quiet

echo ""
echo "[3/3] Iniciando servidor..."
echo ""
echo "========================================"
echo "   Dashboard disponible en:"
echo "   http://localhost:8000"
echo "========================================"
echo ""
echo "Presiona Ctrl+C para detener el servidor"
echo ""

cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
