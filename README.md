# 📧 Sistema de Correos Masivos - Dashboard Local

Sistema local para gestionar envíos masivos de correos usando SendGrid, con dashboard web.

## 🚀 Instalación Rápida

### 1. Crear entorno virtual
```bash
cd CorreosMasivos
python -m venv venv
```

### 2. Activar entorno virtual (IMPORTANTE - hacer siempre)
```bash
.\venv\Scripts\Activate.ps1   # Windows PowerShell
# o: venv\Scripts\activate    # Windows CMD
# o: source venv/bin/activate # Linux/Mac
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar SendGrid
Crear archivo `.env` en la raíz:
```env
SENDGRID_API_KEY=tu_api_key_aqui
SENDGRID_FROM_EMAIL=noreply@tudominio.com
SENDGRID_FROM_NAME=Mi Empresa
```

### 5. Ejecutar
```bash
cd backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 6. Abrir dashboard
Navegar a: http://localhost:8000

---

## 📋 Funcionalidades

### ✅ Crear Campaña
- Editor HTML con vista previa
- Variables dinámicas: `{{email}}`, `{{nombre}}`, etc.
- Carga de Excel/CSV con validación
- Mapeo de columnas
- Adjuntos múltiples

### ✅ Modo DEMO vs REAL
- **DEMO**: Envía solo a lista de emails de prueba
- **REAL**: Envía a todos los destinatarios del Excel
- Botón "Enviar Prueba" para probar 1 correo

### ✅ Monitor en Tiempo Real
- Progreso con porcentaje
- Contador de enviados/errores
- Lista de eventos en vivo (SSE)
- Botón "Detener envío"

### ✅ Configuración
- Workers concurrentes (1-20)
- Reintentos con backoff exponencial
- Pausa entre lotes

---

## 📁 Estructura de Archivos

```
CorreosMasivos/
├── backend/           # API FastAPI
├── frontend/          # UI Web
├── storage/
│   ├── uploads/       # Archivos Excel subidos
│   ├── attachments/   # Adjuntos de correos
│   └── logs/          # Logs CSV por campaña
├── correos.db         # Base de datos SQLite
└── .env               # Configuración (crear manualmente)
```

---

## 🔧 API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/campaigns` | Listar campañas |
| POST | `/api/campaigns` | Crear campaña |
| GET | `/api/campaigns/{id}` | Obtener campaña |
| PUT | `/api/campaigns/{id}` | Actualizar campaña |
| DELETE | `/api/campaigns/{id}` | Eliminar campaña |
| POST | `/api/campaigns/{id}/upload-excel` | Subir Excel |
| POST | `/api/campaigns/{id}/attachments` | Agregar adjunto |
| DELETE | `/api/campaigns/{id}/attachments/{att_id}` | Eliminar adjunto |
| GET | `/api/campaigns/{id}/preview` | Vista previa |
| POST | `/api/campaigns/{id}/send-test` | Enviar prueba |
| POST | `/api/campaigns/{id}/start` | Iniciar envío |
| POST | `/api/campaigns/{id}/stop` | Detener envío |
| GET | `/api/campaigns/{id}/status` | Estado actual |
| GET | `/api/campaigns/{id}/events` | Stream SSE |
| GET | `/api/campaigns/{id}/log` | Descargar CSV |

---

## ⚠️ Límites de Seguridad

- Tamaño máximo de archivo: 10 MB
- Extensiones permitidas: xlsx, xls, csv, pdf, png, jpg, jpeg, gif, doc, docx
- Máximo 10 adjuntos por campaña
- HTML sanitizado automáticamente

---

## 📝 Ejemplo de Excel

| email | nombre | empresa |
|-------|--------|---------|
| juan@mail.com | Juan Pérez | Acme Corp |
| maria@test.com | María García | Tech Inc |

La columna `email` es obligatoria. Las demás son opcionales y se pueden usar como variables en el cuerpo del correo.
