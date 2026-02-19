"""
Gestor de trabajos de envío masivo.
Maneja concurrencia, estado y eventos.
"""
import time
import csv
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from queue import Queue
from pathlib import Path

from config import LOGS_DIR, MAX_WORKERS
from database import get_db_session
from models import Campaign, Recipient, Event
from mailer_service import MailerService, EmailResult
from utils import render_template, get_mime_type


@dataclass
class JobState:
    """Estado de un trabajo de envío."""
    campaign_id: int
    status: str = "pending"  # pending, running, paused, completed, cancelled, error
    total: int = 0
    sent: int = 0
    errors: int = 0
    started_at: Optional[datetime] = None
    stop_requested: bool = False
    pause_requested: bool = False
    events: Queue = field(default_factory=Queue)


class JobManager:
    """
    Gestor de trabajos de envío masivo.
    
    Características:
    - Ejecución en background con ThreadPoolExecutor
    - Control de concurrencia configurable
    - Soporte para pausar/detener
    - Eventos en tiempo real
    - Logs CSV
    """
    
    def __init__(self):
        self.jobs: Dict[int, JobState] = {}
        self.executors: Dict[int, ThreadPoolExecutor] = {}
        self.job_threads: Dict[int, threading.Thread] = {}
        self._lock = threading.Lock()
    
    def start_campaign(
        self,
        campaign_id: int,
        mailer: MailerService,
        on_complete: Optional[Callable] = None
    ) -> bool:
        """
        Inicia el envío de una campaña.
        
        Args:
            campaign_id: ID de la campaña
            mailer: Instancia de MailerService
            on_complete: Callback al completar
        
        Returns:
            True si se inició correctamente
        """
        with self._lock:
            if campaign_id in self.jobs and self.jobs[campaign_id].status == "running":
                return False  # Ya está corriendo
        
        # Crear estado del job
        state = JobState(campaign_id=campaign_id)
        self.jobs[campaign_id] = state
        
        # Iniciar thread principal
        thread = threading.Thread(
            target=self._run_campaign,
            args=(campaign_id, mailer, on_complete),
            daemon=True
        )
        self.job_threads[campaign_id] = thread
        thread.start()
        
        return True
    
    def stop_campaign(self, campaign_id: int) -> bool:
        """Solicita detener una campaña."""
        with self._lock:
            if campaign_id in self.jobs:
                self.jobs[campaign_id].stop_requested = True
                self._add_event(campaign_id, "warning", "Deteniendo envío...")
                return True
        return False
    
    def pause_campaign(self, campaign_id: int) -> bool:
        """Solicita pausar una campaña."""
        with self._lock:
            if campaign_id in self.jobs:
                self.jobs[campaign_id].pause_requested = True
                return True
        return False
    
    def resume_campaign(self, campaign_id: int) -> bool:
        """Resume una campaña pausada."""
        with self._lock:
            if campaign_id in self.jobs:
                self.jobs[campaign_id].pause_requested = False
                self.jobs[campaign_id].status = "running"
                return True
        return False
    
    def get_status(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene el estado actual de una campaña."""
        state = self.jobs.get(campaign_id)
        if not state:
            # Intentar cargar de BD
            with get_db_session() as db:
                campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if campaign:
                    return {
                        "status": campaign.status,
                        "total": campaign.valid_recipients,
                        "sent": campaign.sent_count,
                        "errors": campaign.error_count,
                        "pending": campaign.valid_recipients - campaign.sent_count - campaign.error_count,
                        "progress_percent": (
                            (campaign.sent_count + campaign.error_count) / campaign.valid_recipients * 100
                            if campaign.valid_recipients > 0 else 0
                        ),
                        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
                        "elapsed_seconds": None,
                        "estimated_remaining_seconds": None
                    }
            return None
        
        elapsed = None
        remaining = None
        if state.started_at:
            elapsed = (datetime.utcnow() - state.started_at).total_seconds()
            processed = state.sent + state.errors
            if processed > 0 and state.total > processed:
                rate = processed / elapsed
                remaining = (state.total - processed) / rate if rate > 0 else None
        
        return {
            "status": state.status,
            "total": state.total,
            "sent": state.sent,
            "errors": state.errors,
            "pending": state.total - state.sent - state.errors,
            "progress_percent": (
                (state.sent + state.errors) / state.total * 100
                if state.total > 0 else 0
            ),
            "started_at": state.started_at.isoformat() if state.started_at else None,
            "elapsed_seconds": elapsed,
            "estimated_remaining_seconds": remaining
        }
    
    def get_events(self, campaign_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Obtiene eventos recientes de la cola."""
        state = self.jobs.get(campaign_id)
        events = []
        
        if state:
            # Obtener eventos de la cola sin bloquear
            while not state.events.empty() and len(events) < limit:
                try:
                    events.append(state.events.get_nowait())
                except:
                    break
        
        return events
    
    def _run_campaign(
        self,
        campaign_id: int,
        mailer: MailerService,
        on_complete: Optional[Callable]
    ):
        """Ejecuta el envío de la campaña."""
        state = self.jobs[campaign_id]
        
        try:
            with get_db_session() as db:
                # Cargar campaña
                campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if not campaign:
                    raise ValueError(f"Campaña {campaign_id} no encontrada")
                
                # Cargar destinatarios pendientes
                recipients = db.query(Recipient).filter(
                    Recipient.campaign_id == campaign_id,
                    Recipient.status == "pending"
                ).all()
                
                # Cargar adjuntos fijos (no dinámicos)
                fixed_attachments = [
                    {"path": att.filepath, "filename": att.filename}
                    for att in campaign.attachments
                ]
                
                # Configuración de adjunto dinámico
                dynamic_enabled = campaign.dynamic_attachment_enabled or False
                dynamic_pattern = campaign.dynamic_attachment_pattern or ""
                dynamic_folder = campaign.dynamic_attachment_folder or ""
                
                # PRE-CARGAR lista de PDFs para búsqueda rápida
                pdf_index = {}
                if dynamic_enabled and dynamic_folder:
                    pdf_index = self._build_pdf_index(dynamic_folder)
                    self._add_event(campaign_id, "info", f"Índice de PDFs: {len(pdf_index)} archivos encontrados")
                
                # Preparar estado
                state.total = len(recipients)
                state.status = "running"
                state.started_at = datetime.utcnow()
                
                # Actualizar campaña en BD
                campaign.status = "sending"
                campaign.started_at = state.started_at
                db.commit()
                
                self._add_event(campaign_id, "info", f"Iniciando envío de {state.total} correos")
                
                # Preparar log CSV
                log_path = LOGS_DIR / f"campaign_{campaign_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                csv_file = open(log_path, 'w', newline='', encoding='utf-8')
                csv_writer = csv.writer(csv_file)
                csv_writer.writerow(['timestamp', 'email', 'status', 'attempts', 'message'])
                
                # Determinar emails demo si aplica
                demo_emails = campaign.demo_emails if campaign.demo_mode else []
                demo_index = 0
                
                # Crear ThreadPoolExecutor
                max_workers = campaign.max_workers or MAX_WORKERS
                executor = ThreadPoolExecutor(max_workers=max_workers)
                self.executors[campaign_id] = executor
                
                try:
                    futures = {}
                    
                    for recipient in recipients:
                        # Verificar si se solicitó detener
                        if state.stop_requested:
                            break
                        
                        # Esperar si está pausado
                        while state.pause_requested and not state.stop_requested:
                            state.status = "paused"
                            time.sleep(0.5)
                        
                        if state.stop_requested:
                            break
                        
                        state.status = "running"
                        
                        # Determinar email de destino en modo demo
                        demo_email = None
                        if campaign.demo_mode and demo_emails:
                            demo_email = demo_emails[demo_index % len(demo_emails)]
                            demo_index += 1
                        
                        # Preparar datos del destinatario
                        recipient_data = recipient.data or {}
                        
                        # Calcular adjuntos para este destinatario
                        attachments = list(fixed_attachments)  # Copia de los fijos
                        
                        # Agregar adjunto dinámico si está habilitado
                        if dynamic_enabled and dynamic_folder:
                            try:
                                dynamic_path = None
                                folder_path = Path(dynamic_folder)
                                
                                # MÉTODO 1: Buscar por pattern exacto (case-insensitive en Windows)
                                if dynamic_pattern:
                                    rendered_filename = render_template(dynamic_pattern, recipient_data)
                                    
                                    # Intentar búsqueda exacta primero
                                    exact_path = folder_path / rendered_filename
                                    if exact_path.exists():
                                        dynamic_path = exact_path
                                    else:
                                        # Búsqueda case-insensitive: listar archivos y comparar
                                        rendered_lower = rendered_filename.lower()
                                        for file_in_folder in folder_path.iterdir():
                                            if file_in_folder.name.lower() == rendered_lower:
                                                dynamic_path = file_in_folder
                                                break
                                    
                                    if dynamic_path:
                                        self._add_event(
                                            campaign_id, "debug",
                                            f"Adjunto encontrado por pattern: {dynamic_path.name}",
                                            {"email": recipient.email}
                                        )
                                
                                # MÉTODO 2: Si no hay pattern o no se encontró, buscar por nombre en índice
                                if not dynamic_path and pdf_index:
                                    dynamic_path = self._find_matching_file_fast(
                                        pdf_index, 
                                        recipient_data
                                    )
                                    if dynamic_path:
                                        self._add_event(
                                            campaign_id, "debug",
                                            f"Adjunto encontrado por búsqueda fuzzy: {dynamic_path.name}",
                                            {"email": recipient.email}
                                        )
                                
                                if dynamic_path and dynamic_path.exists():
                                    attachments.append({
                                        "path": str(dynamic_path),
                                        "filename": dynamic_path.name
                                    })
                                else:
                                    nombre = recipient_data.get("Nombre") or recipient_data.get("nombre") or ""
                                    searched_name = render_template(dynamic_pattern, recipient_data) if dynamic_pattern else nombre
                                    self._add_event(
                                        campaign_id, "warning",
                                        f"PDF no encontrado: '{searched_name}' en carpeta '{dynamic_folder}'",
                                        {"email": recipient.email, "searched": searched_name}
                                    )
                            except Exception as e:
                                self._add_event(
                                    campaign_id, "error",
                                    f"Error al procesar adjunto dinámico: {str(e)}",
                                    {"email": recipient.email, "error": str(e)}
                                )
                        
                        # Enviar tarea al executor
                        future = executor.submit(
                            self._send_single,
                            mailer,
                            recipient.email,
                            campaign.subject,
                            campaign.html_body,
                            campaign.text_body,
                            recipient_data,
                            attachments,
                            campaign.demo_mode,
                            demo_email
                        )
                        futures[future] = recipient
                        
                        # Pausa entre envíos si está configurado
                        if campaign.batch_pause > 0:
                            time.sleep(campaign.batch_pause)
                    
                    # Procesar resultados
                    for future in as_completed(futures):
                        if state.stop_requested:
                            break
                        
                        recipient = futures[future]
                        try:
                            result: EmailResult = future.result()
                            
                            # Actualizar estado local
                            if result.success:
                                state.sent += 1
                                level = "success"
                                msg = f"✅ Enviado a {recipient.email}"
                            else:
                                state.errors += 1
                                level = "error"
                                msg = f"❌ Error en {recipient.email}: {result.message}"
                            
                            # Registrar evento
                            self._add_event(campaign_id, level, msg)
                            
                            # Log CSV
                            csv_writer.writerow([
                                datetime.now().isoformat(),
                                recipient.email,
                                "sent" if result.success else "error",
                                result.attempts,
                                result.message
                            ])
                            csv_file.flush()
                            
                            # Actualizar recipient en BD
                            with get_db_session() as db2:
                                rec = db2.query(Recipient).filter(Recipient.id == recipient.id).first()
                                if rec:
                                    rec.status = "sent" if result.success else "error"
                                    rec.error_message = result.message if not result.success else None
                                    rec.attempts = result.attempts
                                    rec.sent_at = datetime.utcnow() if result.success else None
                                    db2.commit()
                            
                        except Exception as e:
                            state.errors += 1
                            self._add_event(campaign_id, "error", f"Error procesando {recipient.email}: {str(e)}")
                    
                finally:
                    csv_file.close()
                    executor.shutdown(wait=False)
                
                # Determinar estado final
                if state.stop_requested:
                    final_status = "cancelled"
                    self._add_event(campaign_id, "warning", "Envío cancelado por usuario")
                elif state.errors > 0 and state.sent == 0:
                    final_status = "error"
                else:
                    final_status = "completed"
                
                state.status = final_status
                
                # Actualizar campaña en BD
                with get_db_session() as db:
                    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                    if campaign:
                        campaign.status = final_status
                        campaign.sent_count = state.sent
                        campaign.error_count = state.errors
                        campaign.completed_at = datetime.utcnow()
                        db.commit()
                
                self._add_event(
                    campaign_id, 
                    "info" if final_status == "completed" else "warning",
                    f"Envío finalizado. Enviados: {state.sent}, Errores: {state.errors}"
                )
                
        except Exception as e:
            state.status = "error"
            self._add_event(campaign_id, "error", f"Error fatal: {str(e)}")
            
            with get_db_session() as db:
                campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if campaign:
                    campaign.status = "error"
                    db.commit()
        
        finally:
            # Limpiar executor
            if campaign_id in self.executors:
                del self.executors[campaign_id]
            
            # Callback de completado
            if on_complete:
                on_complete(campaign_id, state)
    
    def _normalize_text(self, text: str) -> str:
        """Normaliza texto: quita acentos, puntos y convierte a minúsculas."""
        import unicodedata
        import re
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        # Quitar puntos y otros caracteres especiales (excepto espacios)
        text = re.sub(r'[^\w\s]', '', text)
        return text.lower()
    
    def _build_pdf_index(self, folder: str) -> Dict[frozenset, Path]:
        """
        Construye un índice de PDFs para búsqueda rápida.
        Clave: conjunto de palabras normalizadas del nombre del archivo
        Valor: ruta completa al archivo
        
        Se ejecuta UNA VEZ al inicio del envío.
        """
        pdf_index = {}
        folder_path = Path(folder)
        
        if not folder_path.exists():
            return pdf_index
        
        for file_path in folder_path.glob("*.pdf"):
            # Normalizar nombre del archivo (sin extensión)
            filename_normalized = self._normalize_text(file_path.stem)
            palabras = frozenset(filename_normalized.split())
            pdf_index[palabras] = file_path
        
        return pdf_index
    
    def _find_matching_file_fast(
        self, 
        pdf_index: Dict[frozenset, Path],
        recipient_data: Dict[str, Any]
    ) -> Optional[Path]:
        """
        Búsqueda RÁPIDA de PDF usando el índice pre-calculado.
        
        Busca un PDF que contenga todas las palabras del nombre del destinatario.
        """
        # Obtener nombre del destinatario - buscar en varias claves posibles
        nombre_completo = ""
        for key in ["nombres", "Nombres", "NOMBRES", "Nombre", "nombre", "nombre_completo", "NOMBRE"]:
            if key in recipient_data and recipient_data[key]:
                nombre_completo = str(recipient_data[key]).strip()
                break
        
        if not nombre_completo:
            return None
        
        # Palabras del nombre del destinatario (normalizadas)
        palabras_nombre = frozenset(self._normalize_text(nombre_completo).split())
        
        # Buscar coincidencia exacta primero (todas las palabras del nombre están en el archivo)
        for palabras_archivo, file_path in pdf_index.items():
            if palabras_nombre.issubset(palabras_archivo):
                return file_path
        
        # También buscar al revés: todas las palabras del archivo están en el nombre
        # Esto cubre casos donde el archivo tiene menos palabras que el Excel
        for palabras_archivo, file_path in pdf_index.items():
            # Quitar palabras comunes como "invitacion"
            palabras_archivo_filtradas = palabras_archivo - frozenset(['invitacion', 'invitation', 'inv'])
            if palabras_archivo_filtradas.issubset(palabras_nombre):
                return file_path
        
        # Si no hay coincidencia exacta, buscar 80% de coincidencia
        for palabras_archivo, file_path in pdf_index.items():
            coincidencias = palabras_nombre.intersection(palabras_archivo)
            if len(palabras_nombre) > 0 and len(coincidencias) >= len(palabras_nombre) * 0.8:
                return file_path
        
        return None
    
    def _send_single(
        self,
        mailer: MailerService,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str],
        recipient_data: Dict[str, Any],
        attachments: List[Dict[str, Any]],
        demo_mode: bool,
        demo_email: Optional[str]
    ) -> EmailResult:
        """Envía un solo correo."""
        return mailer.send_email(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            recipient_data=recipient_data,
            attachments=attachments,
            demo_mode=demo_mode,
            demo_email=demo_email
        )
    
    def _add_event(self, campaign_id: int, level: str, message: str, details: Dict = None):
        """Agrega evento a la cola y a la BD."""
        state = self.jobs.get(campaign_id)
        
        event_data = {
            "level": level,
            "message": message,
            "details": details,
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Agregar a cola local
        if state:
            state.events.put(event_data)
        
        # Guardar en BD
        try:
            with get_db_session() as db:
                event = Event(
                    campaign_id=campaign_id,
                    level=level,
                    message=message,
                    details=details
                )
                db.add(event)
                db.commit()
        except:
            pass  # No fallar si no se puede guardar evento


# Instancia singleton
_job_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    """Obtiene o crea instancia del JobManager."""
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager
