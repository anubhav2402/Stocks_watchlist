import logging
import httpx

from config import RESEND_API_KEY

logger = logging.getLogger(__name__)

RESEND_URL    = "https://api.resend.com/emails"
FROM_ADDRESS  = "StockPulse Alerts <onboarding@resend.dev>"

_BASE_STYLE = """
  font-family: Georgia, serif;
  background: #faf9f7;
  padding: 32px;
  color: #161413;
"""

_HEAD = """
  <h2 style="font-size:22px;margin-bottom:4px">
    StockPulse <em style="font-style:italic">{title}</em>
  </h2>
  <p style="color:#6b5f53;font-size:13px;margin-bottom:24px">{subtitle}</p>
"""

_TABLE_OPEN = """
  <table style="border-collapse:collapse;width:100%;background:#fff;
    border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)">
  <thead>
    <tr style="background:#161413;color:#fff;font-size:11px;
               text-transform:uppercase;letter-spacing:.07em">
"""

_FOOTER = """
  <p style="font-size:11px;color:#a89b89;margin-top:24px">
    StockPulse · data via Yahoo Finance · 8 AM IST
  </p>
"""


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


def _fmt_price(v) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    arrow = "▲" if v > 0 else "▼"
    color = "#2e7d32" if v > 0 else "#b5341a"
    return f'<span style="color:{color};font-weight:600">{arrow} {abs(v):.2f}%</span>'


def _fmt_change(v) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    color = "#2e7d32" if v > 0 else "#b5341a"
    return f'<span style="color:{color}">{sign}${v:,.2f}</span>'


def build_portfolio_digest_email(stocks: list[dict]) -> str:
    rows = ""
    for s in stocks:
        rows += f"""
        <tr style="border-bottom:1px solid #f0ebe4">
          <td style="padding:10px 16px;font-weight:700;font-size:14px;
                     font-family:'Courier New',monospace;letter-spacing:.04em">
            {s['ticker']}
          </td>
          <td style="padding:10px 16px;font-size:14px">{_fmt_price(s['price'])}</td>
          <td style="padding:10px 16px;font-size:14px">{_fmt_change(s['change'])}</td>
          <td style="padding:10px 16px;font-size:14px">{_fmt_pct(s['pct'])}</td>
        </tr>"""

    return f"""<html><body style="{_BASE_STYLE}">
      {_HEAD.format(title="Daily Portfolio Digest", subtitle="Yesterday&rsquo;s moves across your US portfolio")}
      {_TABLE_OPEN}
        <th style="padding:10px 16px;text-align:left">Ticker</th>
        <th style="padding:10px 16px;text-align:left">Price</th>
        <th style="padding:10px 16px;text-align:left">Change $</th>
        <th style="padding:10px 16px;text-align:left">Change %</th>
      </tr></thead>
      <tbody>{rows}</tbody>
      </table>
      {_FOOTER}
    </body></html>"""


def build_high_beta_email(movers: list[dict]) -> str:
    rows = ""
    for s in movers:
        rows += f"""
        <tr style="border-bottom:1px solid #f0ebe4">
          <td style="padding:10px 16px;font-weight:700;font-size:14px;
                     font-family:'Courier New',monospace;letter-spacing:.04em">
            {s['ticker']}
          </td>
          <td style="padding:10px 16px;font-size:14px">{_fmt_price(s['price'])}</td>
          <td style="padding:10px 16px;font-size:14px">{_fmt_change(s['change'])}</td>
          <td style="padding:10px 16px;font-size:14px">{_fmt_pct(s['pct'])}</td>
        </tr>"""

    return f"""<html><body style="{_BASE_STYLE}">
      {_HEAD.format(
          title="High-Beta Movers",
          subtitle=f"{len(movers)} stock{'s' if len(movers) > 1 else ''} moved &ge;5% in your High-Beta / Software watchlist"
      )}
      {_TABLE_OPEN}
        <th style="padding:10px 16px;text-align:left">Ticker</th>
        <th style="padding:10px 16px;text-align:left">Price</th>
        <th style="padding:10px 16px;text-align:left">Change $</th>
        <th style="padding:10px 16px;text-align:left">Change %</th>
      </tr></thead>
      <tbody>{rows}</tbody>
      </table>
      {_FOOTER}
    </body></html>"""
