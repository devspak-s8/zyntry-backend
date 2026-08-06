from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.services.sendbyte import SendByteError, get_sendbyte_client

logger = logging.getLogger(__name__)


def build_verification_email_html(  # noqa: E501
    token: str, user_name: str | None, app_url: str
) -> str:
    display_name = user_name or "there"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verify Your Email</title>
</head>
<body style="margin:0;padding:0;background-color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">  # noqa: E501
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8fafc;">  # noqa: E501
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">  # noqa: E501
          <tr>
            <td style="background:linear-gradient(135deg,#7c3aed,#6366f1);padding:32px 32px 28px;text-align:center;">  # noqa: E501
              <div style="width:48px;height:48px;background:#ffffff;border-radius:12px;display:inline-flex;align-items:center;justify-content:center;margin-bottom:16px;">  # noqa: E501
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>  # noqa: E501
              </div>
              <h1 style="color:#ffffff;margin:0 0 8px;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Verify Your Email</h1>  # noqa: E501
              <p style="color:rgba(255,255,255,0.85);margin:0;font-size:14px;line-height:1.5;">Welcome to Zyntra, {display_name}!</p>  # noqa: E501
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <p style="color:#334155;margin:0 0 16px;font-size:14px;line-height:1.6;">Your verification code is:</p>  # noqa: E501
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:20px 0;">
                    <table role="presentation" cellpadding="0" cellspacing="0" style="background:#f1f5f9;border-radius:12px;border:2px dashed #cbd5e1;">  # noqa: E501
                      <tr>
                        <td style="padding:16px 32px;text-align:center;">
                          <span style="font-size:32px;font-weight:800;letter-spacing:6px;color:#1e293b;font-family:'SF Mono','Fira Code','Consolas',monospace;">{token}</span>  # noqa: E501
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
              <p style="color:#64748b;margin:0 0 24px;font-size:13px;line-height:1.5;">Enter this code on the verification page to confirm your email address. This code expires in 24 hours.</p>  # noqa: E501
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <a href="{app_url}/verify-email?token={token}" style="display:inline-block;background:#7c3aed;color:#ffffff;padding:14px 28px;border-radius:10px;font-size:14px;font-weight:700;text-decoration:none;box-shadow:0 4px 12px rgba(124,58,237,0.3);">Verify Email Now</a>  # noqa: E501
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="background-color:#f8fafc;padding:20px 32px;border-top:1px solid #e2e8f0;">
              <p style="color:#94a3b8;margin:0;font-size:12px;line-height:1.5;">If you didn't create a Zyntra account, you can safely ignore this email.</p>  # noqa: E501
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_verification_email_text(  # noqa: E501
    token: str, app_url: str
) -> str:
    return (
        f"Your Zyntra verification code is: {token}\n"
        f"\n"
        f"Enter this code at: {app_url}/verify-email\n"
        f"\n"
        f"This code expires in 24 hours.\n"
        f"\n"
        f"If you didn't create a Zyntra account, you can safely ignore this email."
    )


async def send_verification_email(email: str, user_name: str | None, token: str) -> dict[str, Any]:
    if not settings.SENDBYTE_KEY:
        logger.warning("SENDBYTE_KEY is not configured; skipping verification email to %s", email)
        return {"success": False, "error": "email_not_configured"}
    client = get_sendbyte_client()
    app_url = settings.APP_URL
    html = build_verification_email_html(token, user_name, app_url)
    text = build_verification_email_text(token, app_url)
    try:
        result = await client.send(
            to=email,
            subject="Verify your Zyntra email address",
            html=html,
            text=text,
            from_email="noreply@zyntra.ai",
        )
        return {"success": True, "data": result}
    except SendByteError as e:
        logger.error("Failed to send verification email to %s: %s", email, e)
        return {"success": False, "error": str(e)}