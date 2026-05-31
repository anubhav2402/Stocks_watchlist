import logging
import httpx

from config import RESEND_API_KEY

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
FROM_ADDRESS = "StockPulse Alerts <onboarding@resend.dev>"


def send_alert_email(to_email: str, subject: str, html_body: str) -> bool:
    if not RESEND_API_KEY:
        logger.warning("Email alerts not configured — set RESEND_API_KEY in Railway env vars")
        return False
    try:
        r = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": FROM_ADDRESS, "to": [to_email], "subject": subject, "html": html_body},
            timeout=10,
        )
        if r.status_code in (200, 201):
            logger.info("Alert email sent to %s: %s", to_email, subject)
            return True
        logger.error("Resend API error %s: %s", r.status_code, r.text)
        return False
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
        StockPulse · data via Yahoo Finance
      </p>
    </body></html>"""
