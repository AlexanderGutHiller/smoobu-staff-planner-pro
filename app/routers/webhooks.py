"""Webhook routes"""
import logging
from fastapi import APIRouter, Request, Depends, Response
from sqlalchemy.orm import Session

from ..dependencies import get_db
from ..models import Staff
from ..main import log

router = APIRouter(tags=["webhooks"])



# Webhook Routes

# POST /webhook/twilio/status
@router.post("/webhook/twilio/status")
async def twilio_status_webhook(request: Request):
    """Webhook-Endpoint für Twilio Message-Status-Updates"""
    try:
        form_data = await request.form()
        # Twilio sendet Status-Updates als Form-Data
        message_sid = form_data.get("MessageSid", "")
        message_status = form_data.get("MessageStatus", "")
        to_number = form_data.get("To", "")
        from_number = form_data.get("From", "")
        error_code = form_data.get("ErrorCode", "")
        error_message = form_data.get("ErrorMessage", "")
        
        # Entferne "whatsapp:" Präfix für bessere Lesbarkeit
        to_clean = to_number.replace("whatsapp:", "") if to_number.startswith("whatsapp:") else to_number
        from_clean = from_number.replace("whatsapp:", "") if from_number.startswith("whatsapp:") else from_number
        
        # Logge den Status-Update
        if message_status == "delivered":
            log.info("✅ WhatsApp DELIVERED: SID=%s, To=%s, From=%s", 
                    message_sid, to_clean, from_clean)
        elif message_status == "sent":
            log.info("📤 WhatsApp SENT: SID=%s, To=%s, From=%s", 
                    message_sid, to_clean, from_clean)
        elif message_status == "failed":
            log.error("❌ WhatsApp FAILED: SID=%s, To=%s, From=%s, ErrorCode=%s, ErrorMessage=%s", 
                     message_sid, to_clean, from_clean, error_code, error_message)
        elif message_status == "undelivered":
            # Spezifische Fehlermeldungen für bekannte Error Codes
            error_details = ""
            if error_code == "63016":
                error_details = " (24h-Fenster abgelaufen - Vorlage erforderlich oder Sandbox-Nummer nicht verifiziert)"
            elif error_code == "63007":
                error_details = " (Ungültige Telefonnummer)"
            elif error_code == "63014":
                error_details = " (Nachricht zu lang)"
            elif error_code:
                error_details = f" (Code: {error_code})"
            
            log.warning("⚠️ WhatsApp UNDELIVERED: SID=%s, To=%s, From=%s, ErrorCode=%s, ErrorMessage=%s%s", 
                       message_sid, to_clean, from_clean, error_code, error_message or "(keine Details)", error_details)
            
            # Zusätzliche Warnung für 63016 mit Lösungshinweis
            if error_code == "63016":
                log.warning("💡 Lösung für 63016: 1) Im Sandbox-Modus: Nummer verifizieren (Join-Code senden) "
                           "2) Im Production: WhatsApp-Vorlage verwenden für erste Nachricht")
        else:
            log.info("📱 WhatsApp Status Update: SID=%s, Status=%s, To=%s, From=%s", 
                    message_sid, message_status, to_clean, from_clean)
        
        # Return 200 OK für Twilio
        return Response(status_code=200)
    except Exception as e:
        log.error("Error processing Twilio webhook: %s", e, exc_info=True)
        return Response(status_code=500)



# POST /webhook/twilio/message
@router.post("/webhook/twilio/message")
async def twilio_message_webhook(request: Request, db=Depends(get_db)):
    """Webhook-Endpoint für eingehende WhatsApp-Nachrichten (Opt-In-Bestätigung)"""
    try:
        form_data = await request.form()
        from_number = form_data.get("From", "")
        message_body = form_data.get("Body", "").strip().upper()
        
        # Entferne "whatsapp:" Präfix
        from_clean = from_number.replace("whatsapp:", "") if from_number.startswith("whatsapp:") else from_number
        
        log.info("📱 Incoming WhatsApp message from %s: %s", from_clean, message_body)
        
        # Suche Staff-Mitglied mit dieser Telefonnummer
        staff = db.query(Staff).filter(Staff.phone.like(f"%{from_clean}%")).first()
        
        if staff:
            # Normalisiere Telefonnummer für Vergleich
            staff_phone = staff.phone.strip().replace(" ", "").replace("-", "")
            if not staff_phone.startswith("+"):
                if staff_phone.startswith("0"):
                    staff_phone = "+49" + staff_phone[1:]
                else:
                    staff_phone = "+49" + staff_phone
            
            if staff_phone == from_clean:
                # Prüfe ob Nachricht eine Opt-In-Bestätigung ist
                # Typische Bestätigungen: "JA", "YES", "OK", "START", etc.
                opt_in_keywords = ["JA", "YES", "OK", "START", "BEGINNEN", "ANFANGEN", "ZUSTIMMEN", "ACCEPT"]
                if any(keyword in message_body for keyword in opt_in_keywords) or len(message_body) <= 3:
                    # Markiere Opt-In als bestätigt
                    if not staff.whatsapp_opt_in_confirmed:
                        staff.whatsapp_opt_in_confirmed = True
                        db.commit()
                        log.info("✅ Opt-In confirmed for staff %d (%s) via WhatsApp message", staff.id, staff.name)
                    else:
                        log.debug("Opt-In already confirmed for staff %d", staff.id)
                else:
                    log.debug("Message from %s does not appear to be an Opt-In confirmation", from_clean)
        else:
            log.debug("No staff member found with phone number %s", from_clean)
        
        # Return 200 OK für Twilio (immer, auch wenn kein Staff gefunden)
        return Response(status_code=200)
    except Exception as e:
        log.error("Error processing Twilio message webhook: %s", e, exc_info=True)
        return Response(status_code=500)


