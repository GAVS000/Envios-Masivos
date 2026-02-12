"""
Schemas Pydantic para validación de datos.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime


class CampaignCreate(BaseModel):
    """Schema para crear campaña."""
    subject: str = Field(..., min_length=1, max_length=500)
    html_body: str = ""
    text_body: Optional[str] = None
    demo_mode: bool = True
    demo_emails: List[str] = []
    max_workers: int = Field(default=5, ge=1, le=20)
    max_retries: int = Field(default=3, ge=1, le=10)
    batch_pause: float = Field(default=0.0, ge=0.0, le=60.0)
    dynamic_attachment_enabled: bool = False
    dynamic_attachment_pattern: Optional[str] = None
    dynamic_attachment_folder: Optional[str] = None
    
    @field_validator('demo_emails')
    @classmethod
    def validate_demo_emails(cls, v):
        if len(v) > 10:
            raise ValueError('Máximo 10 emails de prueba')
        return v


class CampaignUpdate(BaseModel):
    """Schema para actualizar campaña."""
    subject: Optional[str] = Field(None, min_length=1, max_length=500)
    html_body: Optional[str] = None
    text_body: Optional[str] = None
    demo_mode: Optional[bool] = None
    demo_emails: Optional[List[str]] = None
    email_column: Optional[str] = None
    column_mapping: Optional[Dict[str, str]] = None
    max_workers: Optional[int] = Field(None, ge=1, le=20)
    max_retries: Optional[int] = Field(None, ge=1, le=10)
    batch_pause: Optional[float] = Field(None, ge=0.0, le=60.0)
    dynamic_attachment_enabled: Optional[bool] = None
    dynamic_attachment_pattern: Optional[str] = None
    dynamic_attachment_folder: Optional[str] = None


class CampaignResponse(BaseModel):
    """Schema de respuesta de campaña."""
    id: int
    subject: str
    html_body: str
    text_body: Optional[str]
    demo_mode: bool
    demo_emails: List[str]
    email_column: str
    column_mapping: Dict[str, str]
    excel_filename: Optional[str]
    total_recipients: int
    valid_recipients: int
    max_workers: int
    max_retries: int
    batch_pause: float
    dynamic_attachment_enabled: bool
    dynamic_attachment_pattern: Optional[str]
    dynamic_attachment_folder: Optional[str]
    status: str
    sent_count: int
    error_count: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    attachments: List[Dict[str, Any]] = []
    
    class Config:
        from_attributes = True


class ExcelUploadResponse(BaseModel):
    """Respuesta al subir Excel."""
    success: bool
    filename: str
    total_rows: int
    valid_rows: int
    invalid_emails: List[Dict[str, Any]]
    duplicate_emails: List[str]
    columns: List[str]
    preview: List[Dict[str, Any]]


class PreviewResponse(BaseModel):
    """Respuesta de vista previa del correo."""
    subject: str
    html_body: str
    text_body: Optional[str]
    recipient_data: Dict[str, Any]


class SendTestRequest(BaseModel):
    """Request para enviar correo de prueba."""
    test_email: EmailStr
    row_index: int = 0  # Índice de fila del Excel para usar datos


class SendTestResponse(BaseModel):
    """Respuesta de envío de prueba."""
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None


class StatusResponse(BaseModel):
    """Estado actual de la campaña."""
    status: str
    total: int
    sent: int
    errors: int
    pending: int
    progress_percent: float
    started_at: Optional[datetime]
    elapsed_seconds: Optional[float]
    estimated_remaining_seconds: Optional[float]


class EventResponse(BaseModel):
    """Evento de campaña."""
    id: int
    level: str
    message: str
    details: Optional[Dict[str, Any]]
    created_at: datetime
    
    class Config:
        from_attributes = True
