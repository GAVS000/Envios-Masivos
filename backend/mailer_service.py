"""
Servicio de envío de correos usando SendGrid.
Incluye reintentos con backoff exponencial.
Mejoras de entregabilidad para Microsoft/Hotmail.
"""
import time
import base64
import re
import uuid
from html import unescape
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Email, To, Content, Attachment, FileContent,
    FileName, FileType, Disposition, Header
)

# Dominios de Microsoft que requieren tratamiento especial
MICROSOFT_DOMAINS = {
    'hotmail.com', 'hotmail.es', 'hotmail.co.uk', 'hotmail.fr', 'hotmail.de',
    'outlook.com', 'outlook.es', 'outlook.co.uk', 'outlook.fr', 'outlook.de',
    'live.com', 'live.es', 'live.co.uk', 'live.fr', 'live.de',
    'msn.com', 'passport.com'
}

# Delay adicional para dominios Microsoft (segundos)
MICROSOFT_EXTRA_DELAY = 2.0

from config import (
    SENDGRID_API_KEY, SENDGRID_FROM_EMAIL, SENDGRID_FROM_NAME,
    MAX_RETRIES, RETRY_BASE_DELAY
)
from utils import render_template, get_mime_type


@dataclass
class EmailResult:
    """Resultado de envío de email."""
    success: bool
    email: str
    status_code: Optional[int] = None
    message: str = ""
    attempts: int = 1


def is_microsoft_domain(email: str) -> bool:
    """Detecta si el email pertenece a un dominio de Microsoft."""
    try:
        domain = email.lower().split('@')[1]
        return domain in MICROSOFT_DOMAINS
    except (IndexError, AttributeError):
        return False


def html_to_plain_text(html: str) -> str:
    """Convierte HTML a texto plano básico."""
    # Reemplazar saltos de línea HTML
    text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    # Eliminar todas las etiquetas HTML
    text = re.sub(r'<[^>]+>', '', text)
    # Decodificar entidades HTML
    text = unescape(text)
    # Normalizar espacios
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()


class MailerService:
    """
    Servicio para envío de correos usando SendGrid.
    
    Características:
    - Reintentos con backoff exponencial
    - Soporte para adjuntos
    - Renderizado de plantillas con variables
    - Modo demo (envía a lista fija en lugar de destinatario real)
    - Headers optimizados para Microsoft/Hotmail
    """
    
    def __init__(
        self,
        api_key: str = None,
        from_email: str = None,
        from_name: str = None,
        max_retries: int = None,
        retry_base_delay: float = None
    ):
        self.api_key = api_key or SENDGRID_API_KEY
        self.from_email = from_email or SENDGRID_FROM_EMAIL
        self.from_name = from_name or SENDGRID_FROM_NAME
        self.max_retries = max_retries or MAX_RETRIES
        self.retry_base_delay = retry_base_delay or RETRY_BASE_DELAY
        
        if not self.api_key:
            raise ValueError("SendGrid API key no configurada")
        
        self.client = SendGridAPIClient(self.api_key)
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        recipient_data: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        demo_mode: bool = False,
        demo_email: Optional[str] = None
    ) -> EmailResult:
        """
        Envía un correo con reintentos.
        
        Args:
            to_email: Email del destinatario real
            subject: Asunto del correo (puede contener variables)
            html_body: Cuerpo HTML (puede contener variables)
            text_body: Cuerpo texto plano opcional
            recipient_data: Datos para renderizar variables
            attachments: Lista de adjuntos [{"path": str, "filename": str}]
            demo_mode: Si True, envía a demo_email en lugar de to_email
            demo_email: Email de destino en modo demo
        
        Returns:
            EmailResult con el resultado del envío
        """
        # Determinar destinatario real
        actual_recipient = demo_email if demo_mode and demo_email else to_email
        
        # Preparar datos para renderizar (incluir email original)
        render_data = recipient_data or {}
        render_data['email'] = to_email  # Email original, no el demo
        
        # Renderizar asunto y cuerpo con variables
        rendered_subject = render_template(subject, render_data)
        rendered_html = render_template(html_body, render_data)
        rendered_text = render_template(text_body, render_data) if text_body else None
        
        # IMPORTANTE: Siempre generar texto plano si no existe
        # Microsoft/Hotmail requiere multipart/alternative para buena entregabilidad
        if not rendered_text:
            rendered_text = html_to_plain_text(rendered_html)
        
        # Crear mensaje
        message = Mail(
            from_email=Email(self.from_email, self.from_name),
            to_emails=To(actual_recipient),
            subject=rendered_subject
        )
        
        # IMPORTANTE: El orden debe ser text/plain PRIMERO, luego text/html
        # Esto crea un multipart/alternative correcto que Microsoft acepta mejor
        message.add_content(Content("text/plain", rendered_text))
        message.add_content(Content("text/html", rendered_html))
        
        # Agregar headers importantes para mejorar entregabilidad
        # Especialmente crítico para Microsoft/Hotmail/Outlook
        message_id = f"<{uuid.uuid4()}@{self.from_email.split('@')[1]}>"
        message.add_header(Header("Message-ID", message_id))
        
        # List-Unsubscribe es MUY importante para Microsoft
        # Usar el email de respuesta como unsubscribe básico
        unsubscribe_email = f"mailto:{self.from_email}?subject=unsubscribe"
        message.add_header(Header("List-Unsubscribe", f"<{unsubscribe_email}>"))
        message.add_header(Header("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"))
        
        # Headers adicionales de legitimidad
        message.add_header(Header("X-Priority", "3"))  # Normal priority
        message.add_header(Header("X-Mailer", "SendGrid-MassMailer/1.0"))
        
        # Agregar adjuntos
        if attachments:
            for att in attachments:
                attachment = self._create_attachment(att)
                if attachment:
                    message.add_attachment(attachment)
        
        # Detectar si es dominio Microsoft para delay adicional
        is_microsoft = is_microsoft_domain(actual_recipient)
        
        # Enviar con reintentos
        return self._send_with_retry(message, to_email, is_microsoft)
    
    def _create_attachment(self, att_info: Dict[str, Any]) -> Optional[Attachment]:
        """Crea objeto Attachment de SendGrid."""
        try:
            raw_path = att_info.get('path', '')
            filepath = Path(raw_path)
            filename = att_info.get('filename', filepath.name)
            
            # Verificar que el archivo existe
            if not filepath.exists():
                print(f"[ATTACHMENT ERROR] Archivo no existe: {filepath}")
                return None
            
            # Verificar que es un archivo (no directorio)
            if not filepath.is_file():
                print(f"[ATTACHMENT ERROR] No es un archivo: {filepath}")
                return None
            
            # Leer y codificar el archivo
            with open(filepath, 'rb') as f:
                data = f.read()
            
            if len(data) == 0:
                print(f"[ATTACHMENT ERROR] Archivo vacío: {filepath}")
                return None
            
            encoded = base64.b64encode(data).decode()
            
            attachment = Attachment()
            attachment.file_content = FileContent(encoded)
            attachment.file_name = FileName(filename)
            attachment.file_type = FileType(get_mime_type(filename))
            attachment.disposition = Disposition('attachment')
            
            print(f"[ATTACHMENT OK] {filename} ({len(data)} bytes)")
            return attachment
        except Exception as e:
            print(f"[ATTACHMENT ERROR] Excepción al crear adjunto: {e}")
            return None
    
    def _send_with_retry(self, message: Mail, original_email: str, is_microsoft: bool = False) -> EmailResult:
        """
        Envía mensaje con reintentos y backoff exponencial.
        
        Args:
            message: Mensaje a enviar
            original_email: Email original del destinatario
            is_microsoft: Si True, aplica delay adicional para mejorar entregabilidad
        """
        last_error = ""
        
        # Delay inicial para dominios Microsoft (antes de enviar)
        if is_microsoft:
            time.sleep(MICROSOFT_EXTRA_DELAY)
        
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.send(message)
                
                if response.status_code in (200, 202):
                    return EmailResult(
                        success=True,
                        email=original_email,
                        status_code=response.status_code,
                        message="Enviado correctamente" + (" (Microsoft)" if is_microsoft else ""),
                        attempts=attempt
                    )
                else:
                    last_error = f"Status code: {response.status_code}"
                    
            except Exception as e:
                last_error = str(e)
            
            # Backoff exponencial antes de reintentar
            # Más conservador para Microsoft
            if attempt < self.max_retries:
                base_delay = self.retry_base_delay * (2 if is_microsoft else 1)
                delay = base_delay * (2 ** (attempt - 1))
                time.sleep(delay)
        
        return EmailResult(
            success=False,
            email=original_email,
            message=f"Error después de {self.max_retries} intentos: {last_error}",
            attempts=self.max_retries
        )
    
    def send_test(
        self,
        test_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        sample_data: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> EmailResult:
        """
        Envía un correo de prueba.
        Wrapper conveniente para send_email.
        """
        return self.send_email(
            to_email=test_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            recipient_data=sample_data,
            attachments=attachments,
            demo_mode=False  # En test, enviamos directo al email de prueba
        )
    
    def validate_api_key(self) -> Tuple[bool, str]:
        """Valida que el API key de SendGrid sea válido."""
        try:
            # Intentar obtener info de la cuenta
            response = self.client.client.api_keys.get()
            if response.status_code == 200:
                return True, "API key válida"
            else:
                return False, f"Error: {response.status_code}"
        except Exception as e:
            return False, str(e)


# Instancia singleton para usar en la aplicación
_mailer_instance: Optional[MailerService] = None


def get_mailer() -> MailerService:
    """Obtiene o crea instancia del MailerService."""
    global _mailer_instance
    if _mailer_instance is None:
        _mailer_instance = MailerService()
    return _mailer_instance
