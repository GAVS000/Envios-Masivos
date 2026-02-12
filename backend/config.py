"""
Configuración central del sistema de correos masivos.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Rutas base
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
ATTACHMENTS_DIR = STORAGE_DIR / "attachments"
LOGS_DIR = STORAGE_DIR / "logs"

# Cargar variables de entorno desde el .env en la raíz del proyecto
load_dotenv(BASE_DIR / ".env")

# Crear directorios si no existen
for dir_path in [STORAGE_DIR, UPLOADS_DIR, ATTACHMENTS_DIR, LOGS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Base de datos
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/correos.db")

# SendGrid
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "noreply@example.com")
SENDGRID_FROM_NAME = os.getenv("SENDGRID_FROM_NAME", "Sistema de Correos")

# Configuración de envío
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY", "1.0"))  # segundos
BATCH_PAUSE = float(os.getenv("BATCH_PAUSE", "0.0"))  # segundos entre lotes

# Límites de seguridad
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_ATTACHMENTS = 10
ALLOWED_EXCEL_EXTENSIONS = {".xlsx", ".xls", ".csv"}
ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".doc", ".docx", ".txt", ".zip"}

# Validación
def validate_config():
    """Valida que la configuración esencial esté presente."""
    warnings = []
    
    if not SENDGRID_API_KEY:
        warnings.append("⚠️ SENDGRID_API_KEY no configurada. Los envíos fallarán.")
    
    if SENDGRID_FROM_EMAIL == "noreply@example.com":
        warnings.append("⚠️ SENDGRID_FROM_EMAIL usando valor por defecto.")
    
    return warnings

# Ejecutar validación al importar
CONFIG_WARNINGS = validate_config()
