# 📧 Sistema de Correos Masivos - Dashboard Local

Sistema local para gestionar envíos masivos de correos usando SendGrid, con dashboard web.

## 🚀 Instalación (solo la primera vez)

### 1. Crear entorno virtual
```powershell
cd C:\Users\sergio.gama\Documents\CorreosMasivos
python -m venv venv
```

### 2. Activar entorno virtual
```powershell
.\venv\Scripts\Activate.ps1
```
> Si PowerShell bloquea el script, ejecuta primero: `Set-ExecutionPolicy -Scope Process RemoteSigned`

### 3. Instalar dependencias (solo la primera vez)
```powershell
pip install -r requirements.txt
```
> ⚠️ **Solo necesitas ejecutar esto una vez.** No hay que repetirlo cada vez que uses el sistema.

### 4. Configurar SendGrid (solo la primera vez)
Crear archivo `.env` en la carpeta del proyecto con esto:
```env
SENDGRID_API_KEY=tu_api_key_aqui
SENDGRID_FROM_EMAIL=noreply@tudominio.com
SENDGRID_FROM_NAME=Mi Empresa
```

---

## ▶️ Uso Diario (cada vez que quieras usar el sistema)

### Opción A: Un solo comando (desde la carpeta del proyecto)
```powershell
cd C:\Users\sergio.gama\Documents\CorreosMasivos
.\run.bat
```

### Opción B: Paso a paso manual
```powershell
# 1. Ir a la carpeta del proyecto
cd C:\Users\sergio.gama\Documents\CorreosMasivos

# 2. Activar el entorno virtual (verás "(venv)" al inicio del prompt)
.\venv\Scripts\Activate.ps1

# 3. Ir a la carpeta backend
cd backend

# 4. Ejecutar el servidor
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 5. Abrir el dashboard
Una vez que el servidor esté corriendo, abre en tu navegador: **http://localhost:8000**

> 💡 **¿Cómo sé que funciona?** Verás en la terminal un mensaje como:
> ```
> INFO:     Uvicorn running on http://127.0.0.1:8000
> INFO:     Application startup complete.
> ```

---

## 🔧 Solución de Errores Comunes

| Error | Solución |
|-------|----------|
| `uvicorn: command not found` o `no se reconoce el comando` | No activaste el entorno virtual. Ejecuta `.\venv\Scripts\Activate.ps1` primero |
| `ModuleNotFoundError: No module named 'xxx'` | Ejecuta `pip install -r requirements.txt` |
| `Address already in use` | El puerto 8000 está ocupado. Cierra otras instancias o usa otro puerto: `uvicorn main:app --port 8001` |
| PowerShell bloquea scripts | Ejecuta: `Set-ExecutionPolicy -Scope Process RemoteSigned` |
| `No se encuentra la ruta venv` | No creaste el entorno virtual. Ejecuta `python -m venv venv` |

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

---

## 📬 Entregabilidad a Microsoft (Hotmail/Outlook)

Microsoft tiene los filtros anti-spam más estrictos. El sistema incluye mejoras automáticas, pero necesitas configurar tu dominio correctamente.

### ✅ Mejoras automáticas del sistema
- **Texto plano**: Si no lo proporcionas, se genera automáticamente del HTML
- **Headers**: `List-Unsubscribe`, `Message-ID`, etc. (requeridos por Microsoft)
- **Delay inteligente**: Envíos más lentos a dominios Microsoft (2 seg extra)
- **Backoff conservador**: Reintentos más espaciados para @hotmail/@outlook

### ⚠️ Configuración DNS OBLIGATORIA (en tu proveedor de dominio)
Sin esto, Microsoft rechazará tus correos silenciosamente:

1. **SPF**: Agregar registro TXT
   ```
   v=spf1 include:sendgrid.net ~all
   ```

2. **DKIM**: Configurar en SendGrid → Settings → Sender Authentication → Authenticate Your Domain

3. **DMARC**: Agregar registro TXT
   ```
   _dmarc.tudominio.com  TXT  "v=DMARC1; p=none; rua=mailto:dmarc@tudominio.com"
   ```

### 🔍 Verificar configuración
1. Envía un correo de prueba a [mail-tester.com](https://www.mail-tester.com)
2. Revisa la puntuación (debería ser 9/10 o más)
3. Usa [MXToolbox](https://mxtoolbox.com/spf.aspx) para verificar SPF/DKIM/DMARC

### 💡 Buenas prácticas adicionales
- Usa un dominio propio verificado (no @gmail.com como remitente)
- Incluye enlace de "darse de baja" visible en el cuerpo del correo
- Evita palabras spam: "gratis", "oferta", "urgente", exceso de signos $$$
- No uses SOLO imágenes, siempre incluye texto
- Mantén ratio texto/imagen equilibrado
