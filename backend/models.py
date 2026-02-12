"""
Modelos SQLAlchemy para el sistema de correos masivos.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from database import Base


class Campaign(Base):
    """Modelo de campaña de correo."""
    __tablename__ = "campaigns"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Contenido del correo
    subject = Column(String(500), nullable=False)
    html_body = Column(Text, nullable=False, default="")
    text_body = Column(Text, nullable=True)  # Versión texto plano opcional
    
    # Configuración de modo
    demo_mode = Column(Boolean, default=True)
    demo_emails = Column(JSON, default=list)  # Lista de emails para modo demo
    
    # Mapeo de columnas del Excel
    email_column = Column(String(100), default="email")
    column_mapping = Column(JSON, default=dict)  # {"nombre": "col_nombre", ...}
    
    # Archivo Excel subido
    excel_filename = Column(String(255), nullable=True)
    excel_path = Column(String(500), nullable=True)
    total_recipients = Column(Integer, default=0)
    valid_recipients = Column(Integer, default=0)
    
    # Configuración de envío
    max_workers = Column(Integer, default=5)
    max_retries = Column(Integer, default=3)
    batch_pause = Column(Float, default=0.0)
    
    # Adjunto dinámico/personalizado
    dynamic_attachment_enabled = Column(Boolean, default=False)
    dynamic_attachment_pattern = Column(String(500), nullable=True)  # Ej: "Invitacion {{nombre}} {{apellido}}.pdf"
    dynamic_attachment_folder = Column(String(500), nullable=True)   # Carpeta donde están los PDFs
    
    # Estado
    status = Column(String(50), default="draft")  # draft, sending, paused, completed, cancelled, error
    
    # Progreso
    sent_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relaciones
    recipients = relationship("Recipient", back_populates="campaign", cascade="all, delete-orphan")
    attachments = relationship("Attachment", back_populates="campaign", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="campaign", cascade="all, delete-orphan", order_by="desc(Event.created_at)")
    
    def to_dict(self):
        """Convierte el modelo a diccionario."""
        return {
            "id": self.id,
            "subject": self.subject,
            "html_body": self.html_body,
            "text_body": self.text_body,
            "demo_mode": self.demo_mode,
            "demo_emails": self.demo_emails or [],
            "email_column": self.email_column,
            "column_mapping": self.column_mapping or {},
            "excel_filename": self.excel_filename,
            "total_recipients": self.total_recipients,
            "valid_recipients": self.valid_recipients,
            "max_workers": self.max_workers,
            "max_retries": self.max_retries,
            "batch_pause": self.batch_pause,
            "dynamic_attachment_enabled": self.dynamic_attachment_enabled,
            "dynamic_attachment_pattern": self.dynamic_attachment_pattern,
            "dynamic_attachment_folder": self.dynamic_attachment_folder,
            "status": self.status,
            "sent_count": self.sent_count,
            "error_count": self.error_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "attachments": [a.to_dict() for a in self.attachments] if self.attachments else [],
        }


class Recipient(Base):
    """Modelo de destinatario de campaña."""
    __tablename__ = "recipients"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    
    # Datos del destinatario
    email = Column(String(255), nullable=False)
    data = Column(JSON, default=dict)  # Datos adicionales del Excel (nombre, empresa, etc.)
    
    # Estado de envío
    status = Column(String(50), default="pending")  # pending, sent, error, skipped
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    
    # Relación
    campaign = relationship("Campaign", back_populates="recipients")
    
    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "data": self.data,
            "status": self.status,
            "error_message": self.error_message,
            "attempts": self.attempts,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


class Attachment(Base):
    """Modelo de adjunto de campaña."""
    __tablename__ = "attachments"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    
    # Info del archivo
    filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    mimetype = Column(String(100), nullable=False)
    size = Column(Integer, default=0)  # bytes
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relación
    campaign = relationship("Campaign", back_populates="attachments")
    
    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "mimetype": self.mimetype,
            "size": self.size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Event(Base):
    """Modelo de evento/log de campaña."""
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    
    # Info del evento
    level = Column(String(20), default="info")  # info, success, warning, error
    message = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)  # Datos adicionales
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relación
    campaign = relationship("Campaign", back_populates="events")
    
    def to_dict(self):
        return {
            "id": self.id,
            "level": self.level,
            "message": self.message,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
