"""
Servicio de envío de correos usando SendGrid.
Incluye reintentos con backoff exponencial.
"""
import time
import base64
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Email, To, Content, Attachment, FileContent,
    FileName, FileType, Disposition
)

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


class MailerService:
    """
    Servicio para envío de correos usando SendGrid.
    
    Características:
    - Reintentos con backoff exponencial
    - Soporte para adjuntos
    - Renderizado de plantillas con variables
    - Modo demo (envía a lista fija en lugar de destinatario real)
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
        
        # Crear mensaje
        message = Mail(
            from_email=Email(self.from_email, self.from_name),
            to_emails=To(actual_recipient),
            subject=rendered_subject
        )
        
        # Agregar contenido HTML
        message.add_content(Content("text/html", rendered_html))
        
        # Agregar contenido texto si existe
        if rendered_text:
            message.add_content(Content("text/plain", rendered_text))
        
        # Agregar adjuntos
        if attachments:
            for att in attachments:
                attachment = self._create_attachment(att)
                if attachment:
                    message.add_attachment(attachment)
        
        # Enviar con reintentos
        return self._send_with_retry(message, to_email)
    
    def _create_attachment(self, att_info: Dict[str, Any]) -> Optional[Attachment]:
        """Crea objeto Attachment de SendGrid."""
        try:
            filepath = Path(att_info.get('path', ''))
            filename = att_info.get('filename', filepath.name)
            
            if not filepath.exists():
                return None
            
            with open(filepath, 'rb') as f:
                data = f.read()
            
            encoded = base64.b64encode(data).decode()
            
            attachment = Attachment()
            attachment.file_content = FileContent(encoded)
            attachment.file_name = FileName(filename)
            attachment.file_type = FileType(get_mime_type(filename))
            attachment.disposition = Disposition('attachment')
            
            return attachment
        except Exception:
            return None
    
    def _send_with_retry(self, message: Mail, original_email: str) -> EmailResult:
        """Envía mensaje con reintentos y backoff exponencial."""
        last_error = ""
        
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.send(message)
                
                if response.status_code in (200, 202):
                    return EmailResult(
                        success=True,
                        email=original_email,
                        status_code=response.status_code,
                        message="Enviado correctamente",
                        attempts=attempt
                    )
                else:
                    last_error = f"Status code: {response.status_code}"
                    
            except Exception as e:
                last_error = str(e)
            
            # Backoff exponencial antes de reintentar
            if attempt < self.max_retries:
                delay = self.retry_base_delay * (2 ** (attempt - 1))
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
