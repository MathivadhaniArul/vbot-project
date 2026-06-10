import os
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib

logger = logging.getLogger("email_service")

async def send_reminder_email(to_email: str, event_name: str, event_date: datetime, reminder_offset: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM", "noreply@vbot.edu")
    
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        logger.warning("SMTP configuration is missing. Skipping email sending.")
        return False
        
    try:
        port = int(smtp_port)
    except ValueError:
        logger.error(f"Invalid SMTP port: {smtp_port}")
        return False
        
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔔 Reminder: {event_name}"
    msg["From"] = smtp_from
    msg["To"] = to_email
    
    # Format dates nicely
    date_str = event_date.strftime("%B %d, %Y at %I:%M %p")
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
          <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 20px; text-align: center; color: white;">
            <h1 style="margin: 0; font-size: 24px;">VBOT Assistant Reminder</h1>
          </div>
          <div style="padding: 24px; background-color: #fff;">
            <p>Hello,</p>
            <p>This is a scheduled reminder for your upcoming event:</p>
            
            <div style="background-color: #f8fafc; border-left: 4px solid #4f46e5; padding: 16px; margin: 20px 0; border-radius: 0 4px 4px 0;">
              <h2 style="margin: 0 0 8px 0; font-size: 18px; color: #1e293b;">{event_name}</h2>
              <p style="margin: 0; font-size: 14px; color: #64748b;">
                <strong>Date & Time:</strong> {date_str}
              </p>
              <p style="margin: 4px 0 0 0; font-size: 14px; color: #64748b;">
                <strong>Reminder timing:</strong> {reminder_offset} before the event
              </p>
            </div>
            
            <p style="font-size: 12px; color: #94a3b8; margin-top: 32px; text-align: center;">
              This notification was generated automatically by VBOT College Assistant chatbot.
            </p>
          </div>
        </div>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        use_tls = (port == 465)
        start_tls = (port == 587)
        
        async with aiosmtplib.SMTP(
            hostname=smtp_host,
            port=port,
            use_tls=use_tls,
        ) as client:
            if start_tls:
                await client.starttls()
            await client.login(smtp_user, smtp_pass)
            await client.send_message(msg)
            
        logger.info(f"Reminder email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"SMTP error sending email to {to_email}: {e}")
        return False
