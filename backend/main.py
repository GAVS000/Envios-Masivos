"""
API FastAPI para el sistema de correos masivos.
"""
import os
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from config import (
    BASE_DIR, UPLOADS_DIR, ATTACHMENTS_DIR, LOGS_DIR,
    ALLOWED_EXCEL_EXTENSIONS, ALLOWED_ATTACHMENT_EXTENSIONS,
    MAX_FILE_SIZE, MAX_ATTACHMENTS, CONFIG_WARNINGS
)
from database import get_db, init_db
from models import Campaign, Recipient, Attachment, Event
from schemas import (
    CampaignCreate, CampaignUpdate, CampaignResponse,
    ExcelUploadResponse, PreviewResponse, SendTestRequest, SendTestResponse,
    StatusResponse, EventResponse
)
from utils import (
    validate_file_extension, validate_file_size, 
    read_excel_file, process_excel_recipients, sanitize_html,
    render_template, get_mime_type
)
from mailer_service import get_mailer, MailerService
from job_manager import get_job_manager, JobManager


# Lifespan para inicialización
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Iniciando servidor de correos masivos...")
    init_db()
    
    # Mostrar advertencias de configuración
    for warning in CONFIG_WARNINGS:
        print(warning)
    
    yield
    
    # Shutdown
    print("👋 Deteniendo servidor...")


# Crear app
app = FastAPI(
    title="Sistema de Correos Masivos",
    description="Dashboard local para envío masivo de correos con SendGrid",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos estáticos del frontend
frontend_path = BASE_DIR / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ============================================================================
# ENDPOINTS PRINCIPALES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Sirve la página principal."""
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding='utf-8')
    return "<h1>Frontend no encontrado</h1><p>Cree el archivo frontend/index.html</p>"


@app.get("/api/health")
async def health_check():
    """Endpoint de salud."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "warnings": CONFIG_WARNINGS
    }


# ============================================================================
# CAMPAÑAS
# ============================================================================

@app.get("/api/campaigns", response_model=List[CampaignResponse])
async def list_campaigns(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Lista todas las campañas."""
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).offset(skip).limit(limit).all()
    return [c.to_dict() for c in campaigns]


@app.post("/api/campaigns", response_model=CampaignResponse)
async def create_campaign(
    campaign: CampaignCreate,
    db: Session = Depends(get_db)
):
    """Crea una nueva campaña."""
    db_campaign = Campaign(
        subject=campaign.subject,
        html_body=sanitize_html(campaign.html_body),
        text_body=campaign.text_body,
        demo_mode=campaign.demo_mode,
        demo_emails=campaign.demo_emails,
        max_workers=campaign.max_workers,
        max_retries=campaign.max_retries,
        batch_pause=campaign.batch_pause,
        status="draft"
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign.to_dict()


@app.get("/api/campaigns/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Obtiene una campaña por ID."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    return campaign.to_dict()


@app.put("/api/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: int,
    update: CampaignUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza una campaña."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    if campaign.status == "sending":
        raise HTTPException(status_code=400, detail="No se puede editar una campaña en envío")
    
    update_data = update.model_dump(exclude_unset=True)
    
    # Sanitizar HTML si se actualiza
    if "html_body" in update_data:
        update_data["html_body"] = sanitize_html(update_data["html_body"])
    
    for key, value in update_data.items():
        setattr(campaign, key, value)
    
    db.commit()
    db.refresh(campaign)
    return campaign.to_dict()


@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Elimina una campaña."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    if campaign.status == "sending":
        raise HTTPException(status_code=400, detail="No se puede eliminar una campaña en envío")
    
    # Eliminar archivos asociados
    if campaign.excel_path and Path(campaign.excel_path).exists():
        Path(campaign.excel_path).unlink()
    
    for att in campaign.attachments:
        if Path(att.filepath).exists():
            Path(att.filepath).unlink()
    
    db.delete(campaign)
    db.commit()
    return {"message": "Campaña eliminada"}


# ============================================================================
# EXCEL / DESTINATARIOS
# ============================================================================

@app.post("/api/campaigns/{campaign_id}/upload-excel", response_model=ExcelUploadResponse)
async def upload_excel(
    campaign_id: int,
    file: UploadFile = File(...),
    email_column: str = Form(default="email"),
    db: Session = Depends(get_db)
):
    """Sube archivo Excel/CSV con destinatarios."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    # Validar extensión
    if not validate_file_extension(file.filename, ALLOWED_EXCEL_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido. Use .xlsx, .xls o .csv")
    
    # Leer contenido
    content = await file.read()
    
    # Validar tamaño
    if not validate_file_size(len(content)):
        raise HTTPException(status_code=400, detail="Archivo demasiado grande. Máximo 10MB.")
    
    # Guardar archivo
    file_path = UPLOADS_DIR / f"campaign_{campaign_id}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(content)
    
    try:
        # Leer Excel
        df, columns = read_excel_file(str(file_path))
        
        # Auto-detectar columna de email si es necesario
        actual_email_column = email_column
        if email_column == "auto" or email_column not in columns:
            # Buscar columnas comunes de email
            email_column_candidates = ["email", "correo", "e-mail", "mail", "Email", "CORREO", "E-MAIL", "MAIL", "Correo"]
            actual_email_column = None
            for candidate in email_column_candidates:
                if candidate in columns:
                    actual_email_column = candidate
                    break
            
            # Si no encuentra, buscar columna que contenga "email" o "correo"
            if not actual_email_column:
                for col in columns:
                    col_lower = col.lower()
                    if "email" in col_lower or "correo" in col_lower or "mail" in col_lower:
                        actual_email_column = col
                        break
            
            if not actual_email_column:
                raise HTTPException(
                    status_code=400, 
                    detail=f"No se encontró columna de email. Columnas disponibles: {columns}. Asegúrate de tener una columna llamada 'email' o 'correo'."
                )
        
        # Procesar destinatarios
        valid, invalid, duplicates = process_excel_recipients(df, actual_email_column)
        
        # Eliminar destinatarios anteriores
        db.query(Recipient).filter(Recipient.campaign_id == campaign_id).delete()
        
        # Insertar nuevos destinatarios
        for rec in valid:
            recipient = Recipient(
                campaign_id=campaign_id,
                email=rec["email"],
                data=rec["data"],
                status="pending"
            )
            db.add(recipient)
        
        # Actualizar campaña
        campaign.excel_filename = file.filename
        campaign.excel_path = str(file_path)
        campaign.email_column = actual_email_column
        campaign.total_recipients = len(df)
        campaign.valid_recipients = len(valid)
        
        db.commit()
        
        # Preparar preview (primeras 20 filas)
        preview_data = df.head(20).fillna("").to_dict(orient="records")
        
        return ExcelUploadResponse(
            success=True,
            filename=file.filename,
            total_rows=len(df),
            valid_rows=len(valid),
            invalid_emails=invalid,
            duplicate_emails=duplicates,
            columns=columns,
            preview=preview_data
        )
        
    except Exception as e:
        # Eliminar archivo si falla
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/campaigns/{campaign_id}/recipients")
async def get_recipients(
    campaign_id: int,
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Obtiene destinatarios de una campaña."""
    query = db.query(Recipient).filter(Recipient.campaign_id == campaign_id)
    
    if status:
        query = query.filter(Recipient.status == status)
    
    recipients = query.offset(skip).limit(limit).all()
    total = query.count()
    
    return {
        "total": total,
        "recipients": [r.to_dict() for r in recipients]
    }


# ============================================================================
# ADJUNTOS
# ============================================================================

@app.post("/api/campaigns/{campaign_id}/attachments")
async def upload_attachment(
    campaign_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Sube un adjunto para la campaña."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    # Validar cantidad de adjuntos
    if len(campaign.attachments) >= MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_ATTACHMENTS} adjuntos por campaña")
    
    # Validar extensión
    if not validate_file_extension(file.filename, ALLOWED_ATTACHMENT_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
    
    # Leer contenido
    content = await file.read()
    
    # Validar tamaño
    if not validate_file_size(len(content)):
        raise HTTPException(status_code=400, detail="Archivo demasiado grande. Máximo 10MB.")
    
    # Guardar archivo
    file_path = ATTACHMENTS_DIR / f"campaign_{campaign_id}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Crear registro
    attachment = Attachment(
        campaign_id=campaign_id,
        filename=file.filename,
        filepath=str(file_path),
        mimetype=get_mime_type(file.filename),
        size=len(content)
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    
    return attachment.to_dict()


@app.delete("/api/campaigns/{campaign_id}/attachments/{attachment_id}")
async def delete_attachment(
    campaign_id: int,
    attachment_id: int,
    db: Session = Depends(get_db)
):
    """Elimina un adjunto."""
    attachment = db.query(Attachment).filter(
        Attachment.id == attachment_id,
        Attachment.campaign_id == campaign_id
    ).first()
    
    if not attachment:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    
    # Eliminar archivo
    if Path(attachment.filepath).exists():
        Path(attachment.filepath).unlink()
    
    db.delete(attachment)
    db.commit()
    
    return {"message": "Adjunto eliminado"}


# ============================================================================
# PREVIEW Y PRUEBAS
# ============================================================================

@app.get("/api/campaigns/{campaign_id}/preview", response_model=PreviewResponse)
async def preview_campaign(
    campaign_id: int,
    row_index: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """Genera vista previa del correo con datos de un destinatario."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    # Obtener destinatario para preview
    recipient = db.query(Recipient).filter(
        Recipient.campaign_id == campaign_id
    ).offset(row_index).first()
    
    if not recipient:
        # Usar datos de ejemplo
        recipient_data = {"email": "ejemplo@email.com", "nombre": "Usuario Ejemplo"}
    else:
        recipient_data = recipient.data or {}
        recipient_data["email"] = recipient.email
    
    # Renderizar
    rendered_subject = render_template(campaign.subject, recipient_data)
    rendered_html = render_template(campaign.html_body, recipient_data)
    rendered_text = render_template(campaign.text_body, recipient_data) if campaign.text_body else None
    
    return PreviewResponse(
        subject=rendered_subject,
        html_body=rendered_html,
        text_body=rendered_text,
        recipient_data=recipient_data
    )


@app.post("/api/campaigns/{campaign_id}/send-test", response_model=SendTestResponse)
async def send_test_email(
    campaign_id: int,
    request: SendTestRequest,
    db: Session = Depends(get_db)
):
    """Envía un correo de prueba."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    # Obtener destinatario para datos de muestra
    recipient = db.query(Recipient).filter(
        Recipient.campaign_id == campaign_id
    ).offset(request.row_index).first()
    
    if recipient:
        sample_data = recipient.data or {}
        sample_data["email"] = recipient.email
    else:
        sample_data = {"email": request.test_email, "nombre": "Usuario Prueba"}
    
    # Preparar adjuntos
    attachments = [
        {"path": att.filepath, "filename": att.filename}
        for att in campaign.attachments
    ]
    
    try:
        mailer = get_mailer()
        result = mailer.send_test(
            test_email=request.test_email,
            subject=campaign.subject,
            html_body=campaign.html_body,
            text_body=campaign.text_body,
            sample_data=sample_data,
            attachments=attachments
        )
        
        # Registrar evento
        event = Event(
            campaign_id=campaign_id,
            level="success" if result.success else "error",
            message=f"Prueba a {request.test_email}: {result.message}"
        )
        db.add(event)
        db.commit()
        
        return SendTestResponse(
            success=result.success,
            message=result.message,
            details={"attempts": result.attempts, "status_code": result.status_code}
        )
        
    except Exception as e:
        return SendTestResponse(
            success=False,
            message=str(e)
        )


# ============================================================================
# ENVÍO MASIVO
# ============================================================================

@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Inicia el envío masivo de una campaña."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    if campaign.status == "sending":
        raise HTTPException(status_code=400, detail="La campaña ya está en envío")
    
    if campaign.valid_recipients == 0:
        raise HTTPException(status_code=400, detail="No hay destinatarios válidos")
    
    if campaign.demo_mode and not campaign.demo_emails:
        raise HTTPException(status_code=400, detail="Modo DEMO activo pero no hay emails de prueba configurados")
    
    # Resetear destinatarios si es re-envío
    if campaign.status in ("completed", "cancelled", "error"):
        db.query(Recipient).filter(
            Recipient.campaign_id == campaign_id
        ).update({"status": "pending", "attempts": 0, "error_message": None})
        campaign.sent_count = 0
        campaign.error_count = 0
        db.commit()
    
    try:
        mailer = get_mailer()
        job_manager = get_job_manager()
        
        success = job_manager.start_campaign(campaign_id, mailer)
        
        if not success:
            raise HTTPException(status_code=400, detail="No se pudo iniciar el envío")
        
        return {"message": "Envío iniciado", "campaign_id": campaign_id}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Detiene el envío de una campaña."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    job_manager = get_job_manager()
    success = job_manager.stop_campaign(campaign_id)
    
    if success:
        return {"message": "Solicitud de detención enviada"}
    else:
        raise HTTPException(status_code=400, detail="No hay envío activo para esta campaña")


@app.get("/api/campaigns/{campaign_id}/status", response_model=StatusResponse)
async def get_campaign_status(campaign_id: int, db: Session = Depends(get_db)):
    """Obtiene el estado actual del envío."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    job_manager = get_job_manager()
    status = job_manager.get_status(campaign_id)
    
    if status:
        return status
    
    # Fallback a datos de BD
    return StatusResponse(
        status=campaign.status,
        total=campaign.valid_recipients,
        sent=campaign.sent_count,
        errors=campaign.error_count,
        pending=campaign.valid_recipients - campaign.sent_count - campaign.error_count,
        progress_percent=(
            (campaign.sent_count + campaign.error_count) / campaign.valid_recipients * 100
            if campaign.valid_recipients > 0 else 0
        ),
        started_at=campaign.started_at,
        elapsed_seconds=None,
        estimated_remaining_seconds=None
    )


# ============================================================================
# EVENTOS (SSE)
# ============================================================================

@app.get("/api/campaigns/{campaign_id}/events")
async def stream_events(campaign_id: int, db: Session = Depends(get_db)):
    """Stream de eventos en tiempo real (Server-Sent Events)."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    async def event_generator():
        job_manager = get_job_manager()
        last_event_id = 0
        
        while True:
            # Obtener nuevos eventos de la cola
            events = job_manager.get_events(campaign_id, limit=10)
            
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
            
            # También enviar estado actual
            status = job_manager.get_status(campaign_id)
            if status:
                yield f"event: status\ndata: {json.dumps(status)}\n\n"
                
                # Terminar si completado
                if status["status"] in ("completed", "cancelled", "error"):
                    yield f"event: done\ndata: {json.dumps({'status': status['status']})}\n\n"
                    break
            
            await asyncio.sleep(0.5)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/campaigns/{campaign_id}/events/history")
async def get_events_history(
    campaign_id: int,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Obtiene historial de eventos de la BD."""
    events = db.query(Event).filter(
        Event.campaign_id == campaign_id
    ).order_by(Event.created_at.desc()).limit(limit).all()
    
    return [e.to_dict() for e in events]


# ============================================================================
# LOGS
# ============================================================================

@app.get("/api/campaigns/{campaign_id}/log")
async def download_log(campaign_id: int, db: Session = Depends(get_db)):
    """Descarga el log CSV de una campaña."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    
    # Buscar archivo de log más reciente
    log_pattern = f"campaign_{campaign_id}_*.csv"
    log_files = sorted(LOGS_DIR.glob(log_pattern), reverse=True)
    
    if not log_files:
        raise HTTPException(status_code=404, detail="No hay log disponible")
    
    return FileResponse(
        log_files[0],
        media_type="text/csv",
        filename=f"log_campaign_{campaign_id}.csv"
    )


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
