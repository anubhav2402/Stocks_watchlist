import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import ALERT_SMTP_USER, ALERT_SMTP_PASSWORD

logger = logging.getLogger(__name__)


def send_alert_email(to_email: str, subject: str, html_body: str) -> bool:
    if not ALERT_SMTP_USER or not ALERT_SMTP_PASSWORD:
        logger.warning("Email alerts not configured (ALERT_SMTP_USER / ALERT_SMTP_PASSWORD not set)")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"StockPulse Alerts <{ALERT_SMTP_USER}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls(context=ctx)
            server.login(ALERT_SMTP_USER, ALERT_SMTP_PASSWORD)
            server.sendmail(ALERT_SMTP_USER, to_email, msg.as_string())
        logger.info("Alert email sent to %s: %s", to_email, subject)
        return True
    except Exception as e:
        logger.error("Failed to send alert email to %s: %s", to_email, e)
        return False


def build_alert_email(alerts: list[dict]) -> str:
    rows = ""
    for a in alerts:
        color = "#2e7d32" if a["type"] == "target_hit" else "#b5341a"
        rows += f"""
        <tr>
          <td style="padding:10px 16px;font-weight:600;font-size:15px">{a['ticker']}</td>
          <td style="padding:10px 16px">{a['message']}</td>
          <td style="padding:10px 16px;color:{color};font-weight:600">{a['detail']}</td>
        </tr>"""

    return f"""
    <html><body style="font-family:Georgia,serif;background:#faf9f7;padding:32px;color:#161413">
      <h2 style="font-size:22px;margin-bottom:4px">StockPulse <em style="font-style:italic">Alerts</em></h2>
      <p style="color:#6b5f53;font-size:13px;margin-bottom:24px">
        {len(alerts)} alert{"s" if len(alerts) > 1 else ""} triggered
      </p>
      <table style="border-collapse:collapse;width:100%;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)">
        <thead>
          <tr style="background:#161413;color:#fff;font-size:12px;text-transform:uppercase;letter-spacing:.05em">
            <th style="padding:10px 16px;text-align:left">Ticker</th>
            <th style="padding:10px 16px;text-align:left">Alert</th>
            <th style="padding:10px 16px;text-align:left">Detail</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="font-size:11px;color:#a89b89;margin-top:24px">
        StockPulse · data via Yahoo Finance · manage alerts at stockswatchlist.github.io
      </p>
    </body></html>"""
