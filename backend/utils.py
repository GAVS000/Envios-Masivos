"""
Utilidades varias para el sistema de correos masivos.
"""
import re
import hashlib
from typing import Dict, Any, List, Tuple
from pathlib import Path
import pandas as pd
from email_validator import validate_email, EmailNotValidError
import bleach
from jinja2 import Template, Environment, BaseLoader, TemplateSyntaxError

from config import ALLOWED_EXCEL_EXTENSIONS, ALLOWED_ATTACHMENT_EXTENSIONS, MAX_FILE_SIZE


def validate_file_extension(filename: str, allowed: set) -> bool:
    """Valida que la extensión del archivo esté permitida."""
    ext = Path(filename).suffix.lower()
    return ext in allowed


def validate_file_size(size: int) -> bool:
    """Valida que el tamaño del archivo esté dentro del límite."""
    return size <= MAX_FILE_SIZE


def is_valid_email(email: str) -> bool:
    """Valida formato de email."""
    if not email or not isinstance(email, str):
        return False
    try:
        validate_email(email.strip(), check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def sanitize_html(html: str) -> str:
    """
    Sanitiza HTML para prevenir XSS.
    Permite tags comunes de email pero remueve scripts.
    """
    allowed_tags = [
        'a', 'abbr', 'acronym', 'address', 'b', 'big', 'blockquote', 'br',
        'center', 'cite', 'code', 'col', 'colgroup', 'dd', 'del', 'dfn',
        'dir', 'div', 'dl', 'dt', 'em', 'font', 'h1', 'h2', 'h3', 'h4',
        'h5', 'h6', 'hr', 'i', 'img', 'ins', 'kbd', 'li', 'ol', 'p', 'pre',
        'q', 's', 'samp', 'small', 'span', 'strike', 'strong', 'sub', 'sup',
        'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'tt', 'u', 'ul',
        'var'
    ]
    
    allowed_attrs = {
        '*': ['class', 'style', 'id'],
        'a': ['href', 'title', 'target'],
        'img': ['src', 'alt', 'width', 'height'],
        'font': ['color', 'face', 'size'],
        'table': ['border', 'cellpadding', 'cellspacing', 'width'],
        'td': ['colspan', 'rowspan', 'width', 'height', 'align', 'valign'],
        'th': ['colspan', 'rowspan', 'width', 'height', 'align', 'valign'],
    }
    
    return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)


def render_template(template_str: str, data: Dict[str, Any]) -> str:
    """
    Renderiza una plantilla con variables.
    Soporta sintaxis {{variable}} y {{ variable }}.
    """
    try:
        # Crear environment de Jinja2
        env = Environment(loader=BaseLoader())
        
        # Convertir sintaxis {{var}} a {{ var }} si es necesario
        # Jinja2 ya soporta ambas
        template = env.from_string(template_str)
        
        # Renderizar con datos
        return template.render(**data)
    except TemplateSyntaxError as e:
        # Si hay error de sintaxis, devolver original
        return template_str
    except Exception:
        return template_str


def extract_variables(template_str: str) -> List[str]:
    """Extrae las variables usadas en una plantilla."""
    # Buscar patrones {{variable}} o {{ variable }}
    pattern = r'\{\{\s*(\w+)\s*\}\}'
    matches = re.findall(pattern, template_str)
    return list(set(matches))


def read_excel_file(filepath: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    Lee archivo Excel/CSV y devuelve DataFrame y lista de columnas.
    """
    path = Path(filepath)
    ext = path.suffix.lower()
    
    if ext == '.csv':
        # Intentar diferentes encodings
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                df = pd.read_csv(filepath, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("No se pudo leer el archivo CSV con ningún encoding conocido")
    elif ext == '.xlsx':
        df = pd.read_excel(filepath, engine='openpyxl')
    elif ext == '.xls':
        df = pd.read_excel(filepath, engine='xlrd')
    else:
        raise ValueError(f"Extensión no soportada: {ext}")
    
    # Limpiar nombres de columnas
    df.columns = [str(col).strip() for col in df.columns]
    
    return df, list(df.columns)


def process_excel_recipients(
    df: pd.DataFrame,
    email_column: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    Procesa DataFrame de Excel y extrae destinatarios.
    
    Returns:
        - valid_recipients: Lista de diccionarios con email y datos
        - invalid_rows: Lista de filas con emails inválidos
        - duplicate_emails: Lista de emails duplicados
    """
    valid_recipients = []
    invalid_rows = []
    seen_emails = set()
    duplicate_emails = []
    
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        
        # Obtener email
        email_raw = row_dict.get(email_column, "")
        if pd.isna(email_raw):
            email_raw = ""
        email = str(email_raw).strip().lower()
        
        # Validar email
        if not is_valid_email(email):
            invalid_rows.append({
                "row": idx + 2,  # +2 porque Excel empieza en 1 y tiene header
                "email": email_raw,
                "reason": "Email inválido"
            })
            continue
        
        # Verificar duplicados
        if email in seen_emails:
            duplicate_emails.append(email)
            continue
        
        seen_emails.add(email)
        
        # Convertir valores NaN a string vacío
        clean_data = {}
        for key, value in row_dict.items():
            if pd.isna(value):
                clean_data[key] = ""
            else:
                clean_data[key] = str(value)
        
        valid_recipients.append({
            "email": email,
            "data": clean_data
        })
    
    return valid_recipients, invalid_rows, list(set(duplicate_emails))


def generate_file_hash(content: bytes) -> str:
    """Genera hash MD5 de contenido de archivo."""
    return hashlib.md5(content).hexdigest()


def format_file_size(size_bytes: int) -> str:
    """Formatea tamaño de archivo en unidades legibles."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_mime_type(filename: str) -> str:
    """Obtiene MIME type basado en extensión."""
    ext = Path(filename).suffix.lower()
    mime_types = {
        '.pdf': 'application/pdf',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.txt': 'text/plain',
        '.zip': 'application/zip',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.csv': 'text/csv',
    }
    return mime_types.get(ext, 'application/octet-stream')
