from __future__ import annotations

import logging
from html import escape
from typing import Any

from app.core.config import settings
from app.services.sendbyte import SendByteError, get_sendbyte_client

logger = logging.getLogger(__name__)

_APP_NAME = "Zyntra"
_APP_URL = settings.APP_URL or "https://app.zyntry.ai"
_EMAIL_ASSET_BASE_URL = settings.EMAIL_ASSET_BASE_URL.rstrip("/")


_BASE_STYLE = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
"""

_BASE_BG = "#f8fafc"
_CARD_BG = "#ffffff"
_ACCENT_BG = "#2563eb"
_TEXT_PRIMARY = "#334155"
_TEXT_SECONDARY = "#64748b"
_BORDER = "#e2e8f0"
_ACCENT = "#2563eb"


def _email_visual_category(name: str | None, title: str) -> str:
    context = f"{name or ''} {title}".lower()
    categories = (
        (
            "security",
            (
                "auth",
                "password",
                "verify",
                "login",
                "security",
                "mfa",
                "api key",
                "oauth",
                "abuse",
                "permission",
                "account deletion",
            ),
        ),
        (
            "billing",
            (
                "billing",
                "payment",
                "wallet",
                "credit",
                "invoice",
                "subscription",
                "refund",
                "balance",
                "purchase",
            ),
        ),
        (
            "knowledge",
            ("knowledge", "document", "source", "sync", "embedding", "model"),
        ),
        (
            "operations",
            (
                "incident",
                "maintenance",
                "status",
                "health",
                "support",
                "usage",
                "unhealthy",
                "recovered",
                "alert",
            ),
        ),
    )
    for category, keywords in categories:
        if any(keyword in context for keyword in keywords):
            return category
    return "platform"


def build_email(
    title: str,
    subtitle: str,
    body_html: str,
    cta_text: str | None = None,
    cta_url: str | None = None,
    footer_text: str | None = None,
    name: str | None = None,
) -> str:
    accent = _ACCENT
    footer = footer_text or "If you didn't expect this email, you can safely ignore it."
    category = _email_visual_category(name, title)
    logo_url = f"{_EMAIL_ASSET_BASE_URL}/zyntry-logo.jpeg"
    visual_url = f"{_EMAIL_ASSET_BASE_URL}/{category}.png"
    brand_logo = (
        f'<img src="{logo_url}" width="64" height="64" alt="Zyntry" '
        'style="display:block;width:64px;height:64px;object-fit:contain;border-radius:14px;'
        'background:#ffffff;margin:0 auto 16px;border:0;" />'
    )
    cta = ""
    if cta_text and cta_url:
        cta = f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center"><a href="{cta_url}" style="display:inline-block;background:{accent};color:#ffffff;padding:14px 28px;border-radius:10px;font-size:14px;font-weight:700;text-decoration:none;box-shadow:0 4px 12px rgba(124,58,237,0.3);">{cta_text}</a></td></tr></table>'''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>{_BASE_STYLE}</style>
</head>
<body style="background-color:{_BASE_BG};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_BASE_BG};">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background-color:{_CARD_BG};border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
          <tr>
            <td background="{visual_url}" style="background-color:#eff6ff;background-image:url('{visual_url}');background-repeat:no-repeat;background-position:center;background-size:cover;padding:28px 32px;text-align:center;">
              {brand_logo}
              <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto;background:rgba(255,255,255,0.92);border-radius:12px;">
                <tr>
                  <td style="padding:14px 20px;text-align:center;">
                    <h1 style="color:#172554;margin:0 0 6px;font-size:22px;font-weight:700;letter-spacing:-0.3px;">{title}</h1>
                    <p style="color:#334155;margin:0;font-size:14px;line-height:1.5;">{subtitle}</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <p style="color:{_TEXT_PRIMARY};margin:0 0 16px;font-size:14px;line-height:1.6;">{body_html}</p>
              {cta}
            </td>
          </tr>
          <tr>
            <td style="background-color:#f8fafc;padding:20px 32px;border-top:1px solid {_BORDER};">
              <p style="color:{_TEXT_SECONDARY};margin:0;font-size:12px;line-height:1.5;">{footer}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def build_email_text(title: str, body: str, cta_text: str | None = None, cta_url: str | None = None) -> str:
    lines = [title, "=" * len(title), "", body]
    if cta_text and cta_url:
        lines.extend(["", cta_text, cta_url])
    lines.extend(["", "If you didn't expect this email, you can safely ignore it."])
    return "\n".join(lines)


def build_welcome_email(user_name: str | None = None) -> tuple[str, str]:
    display = user_name or "there"
    html = build_email(
        name="welcome",
        title=f"Welcome to {_APP_NAME}",
        subtitle=f"Hello {display}!",
        body_html=f"Your account has been created successfully. You can now start building AI-powered runtimes, connecting knowledge sources, and configuring tools. <a href='{_APP_URL}/dashboard' style='color:{_ACCENT};'>Go to your dashboard</a> to get started.",
        cta_text="Go to Dashboard",
        cta_url=f"{_APP_URL}/dashboard",
        footer_text="If you didn't create a Zyntra account, please contact support.",
    )
    text = build_email_text(
        title=f"Welcome to {_APP_NAME}",
        body=f"Your account has been created successfully. You can now start building AI-powered runtimes, connecting knowledge sources, and configuring tools.\n\nGo to: {_APP_URL}/dashboard",
        cta_text="Go to Dashboard",
        cta_url=f"{_APP_URL}/dashboard",
    )
    return html, text


def build_verify_email(user_name: str | None, token: str) -> tuple[str, str]:
    display = user_name or "there"
    html = build_email(
        name="verify_email",
        title="Verify your email address",
        subtitle=f"Welcome to {_APP_NAME}, {display}!",
        body_html=f"Your verification code is:</p><table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:20px 0;\"><table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f1f5f9;border-radius:12px;border:2px dashed #cbd5e1;\"><tr><td style=\"padding:16px 32px;text-align:center;\"><span style=\"font-size:32px;font-weight:800;letter-spacing:6px;color:#1e293b;font-family:'SF Mono','Fira Code','Consolas',monospace;\">{token}</span></td></tr></table></td></tr></table><p style=\"color:#64748b;margin:0 0 24px;font-size:13px;line-height:1.5;\">Enter this code on the verification page to confirm your email address. This code expires in 24 hours.",
        cta_text="Verify Email Now",
        cta_url=f"{_APP_URL}/verify-email?token={token}",
        footer_text="If you didn't create a Zyntra account, you can safely ignore this email.",
    )
    text = build_email_text(
        title="Verify your email address",
        body=f"Your Zyntra verification code is: {token}\n\nEnter this code at: {_APP_URL}/verify-email\n\nThis code expires in 24 hours.",
        cta_text="Verify Email Now",
        cta_url=f"{_APP_URL}/verify-email?token={token}",
    )
    return html, text


def build_password_reset(user_name: str | None, token: str) -> tuple[str, str]:
    display = user_name or "there"
    html = build_email(
        name="password_reset",
        title="Reset your password",
        subtitle=f"Hi {display},",
        body_html=f"We received a request to reset your password. Enter this code in the app:</p><table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:20px 0;\"><table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f1f5f9;border-radius:12px;border:2px dashed #cbd5e1;\"><tr><td style=\"padding:16px 32px;text-align:center;\"><span style=\"font-size:32px;font-weight:800;letter-spacing:6px;color:#1e293b;font-family:'SF Mono','Fira Code','Consolas',monospace;\">{token}</span></td></tr></table></td></tr></table><p style=\"color:#64748b;margin:0 0 24px;font-size:13px;line-height:1.5;\">This code expires in 15 minutes and can only be used once.",
        cta_text="Enter Reset Code",
        cta_url=f"{_APP_URL}/reset-password",
    )
    text = build_email_text(
        title="Reset your password",
        body=f"We received a request to reset your password.\n\nYour reset code is: {token}\n\nThis code expires in 15 minutes and can only be used once.",
        cta_text="Enter Reset Code",
        cta_url=f"{_APP_URL}/reset-password",
    )
    return html, text


def build_project_created(user_name: str | None, project_name: str) -> tuple[str, str]:
    display = user_name or "there"
    html = build_email(
        title="Project created successfully",
        subtitle=f"Hi {display},",
        body_html=f"Your project <strong>{project_name}</strong> has been created. You can now connect tools, configure runtimes, and start building.",
        cta_text="View Project",
        cta_url=f"{_APP_URL}/projects",
    )
    text = build_email_text(
        title="Project created successfully",
        body=f"Your project '{project_name}' has been created. Go to {_APP_URL}/projects to get started.",
        cta_text="View Project",
        cta_url=f"{_APP_URL}/projects",
    )
    return html, text


def build_runtime_ready(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Your runtime is ready",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime has been successfully built and is now active. You can start sending requests to the runtime API endpoint using your API key.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text(
        title="Your runtime is ready",
        body=f"Runtime '{runtime_name}' has been successfully built and is now active.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    return html, text


def build_runtime_failed(runtime_name: str, error: str | None) -> tuple[str, str]:
    err = error or "An unknown error occurred during the build."
    html = build_email(
        title="Runtime build failed",
        subtitle=f"Runtime '{runtime_name}'",
        body_html=f"The runtime build could not be completed. Error details: <code style=\"background:#f1f5f9;padding:4px 8px;border-radius:4px;font-size:13px;color:#dc2626;\">{err}</code><br><br>Please check the runtime configuration and try rebuilding.",
        cta_text="View Build Logs",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text(
        title="Runtime build failed",
        body=f"Runtime '{runtime_name}' could not be built. Error: {err}\n\nPlease check the configuration and try rebuilding.",
        cta_text="View Build Logs",
        cta_url=f"{_APP_URL}/runtimes",
    )
    return html, text


def build_runtime_sync_finished(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime synchronization completed",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime has been successfully re-synchronized. All connected sources, tools, and knowledge bases have been updated.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text(
        title="Runtime synchronization completed",
        body=f"Runtime '{runtime_name}' has been re-synchronized successfully.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    return html, text


def build_runtime_sync_failed(runtime_name: str, error: str | None) -> tuple[str, str]:
    err = error or "An unknown error occurred during synchronization."
    html = build_email(
        title="Runtime synchronization failed",
        subtitle=f"Runtime '{runtime_name}'",
        body_html=f"The runtime synchronization could not be completed. Error: <code style=\"background:#f1f5f9;padding:4px 8px;border-radius:4px;font-size:13px;color:#dc2626;\">{err}</code>",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text(
        title="Runtime synchronization failed",
        body=f"Runtime '{runtime_name}' sync failed. Error: {err}",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    return html, text


def build_runtime_paused(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime paused",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime has been paused. It will not process any incoming requests until resumed.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime paused", f"Runtime '{runtime_name}' has been paused.", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


def build_runtime_resumed(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime resumed",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime has been resumed and is now active.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime resumed", f"Runtime '{runtime_name}' has been resumed.", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


def build_runtime_deleted(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime deleted",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime has been permanently deleted. All associated data has been removed.",
        cta_text="View Runtimes",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime deleted", f"Runtime '{runtime_name}' has been permanently deleted.", "View Runtimes", f"{_APP_URL}/runtimes")
    return html, text


def build_source_sync_finished(source_name: str, documents: int) -> tuple[str, str]:
    html = build_email(
        title="Source synchronization completed",
        subtitle=f"Source '{source_name}'",
        body_html=f"The source has been successfully synchronized. {documents} documents were processed and indexed.",
        cta_text="View Source",
        cta_url=f"{_APP_URL}/sources",
    )
    text = build_email_text("Source synchronization completed", f"Source '{source_name}' synced. {documents} documents processed.", "View Source", f"{_APP_URL}/sources")
    return html, text


def build_source_sync_failed(source_name: str, error: str | None) -> tuple[str, str]:
    err = error or "An unknown error occurred."
    html = build_email(
        title="Source synchronization failed",
        subtitle=f"Source '{source_name}'",
        body_html=f"The source synchronization could not be completed. Error: <code style=\"background:#f1f5f9;padding:4px 8px;border-radius:4px;font-size:13px;color:#dc2626;\">{err}</code>",
        cta_text="View Source",
        cta_url=f"{_APP_URL}/sources",
    )
    text = build_email_text("Source synchronization failed", f"Source '{source_name}' sync failed. Error: {err}", "View Source", f"{_APP_URL}/sources")
    return html, text


def build_source_reauth(provider: str) -> tuple[str, str]:
    html = build_email(
        title="Source requires reauthentication",
        subtitle=f"{provider} connection",
        body_html=f"Your {provider} connection has expired or been revoked. Please re-authenticate to continue syncing.",
        cta_text="Reconnect Source",
        cta_url=f"{_APP_URL}/sources",
    )
    text = build_email_text("Source requires reauthentication", f"Your {provider} connection has expired. Re-authenticate at: {_APP_URL}/sources", "Reconnect Source", f"{_APP_URL}/sources")
    return html, text


def build_tool_connected(tool_name: str) -> tuple[str, str]:
    html = build_email(
        title=f"{tool_name} connected successfully",
        subtitle="Tool connection",
        body_html=f"The {tool_name} tool has been successfully connected and is ready to use.",
        cta_text="View Tools",
        cta_url=f"{_APP_URL}/tools",
    )
    text = build_email_text(f"{tool_name} connected successfully", f"The {tool_name} tool is connected and ready.", "View Tools", f"{_APP_URL}/tools")
    return html, text


def build_tool_expired(tool_name: str) -> tuple[str, str]:
    html = build_email(
        title="Tool connection expired",
        subtitle=f"{tool_name}",
        body_html=f"The {tool_name} tool connection has expired. Please reconnect to continue using it.",
        cta_text="Reconnect Tool",
        cta_url=f"{_APP_URL}/tools",
    )
    text = build_email_text("Tool connection expired", f"The {tool_name} tool connection has expired.", "Reconnect Tool", f"{_APP_URL}/tools")
    return html, text


def build_api_key_created(key_name: str) -> tuple[str, str]:
    html = build_email(
        title="API key created",
        subtitle=f"Key: {key_name}",
        body_html=f"Your API key '{key_name}' has been created successfully. Make sure to copy the key now — it won't be shown again.",
        cta_text="Manage API Keys",
        cta_url=f"{_APP_URL}/api-keys",
    )
    text = build_email_text("API key created", f"API key '{key_name}' created. Copy it now — it won't be shown again.", "Manage API Keys", f"{_APP_URL}/api-keys")
    return html, text


def build_api_key_rotated(key_name: str) -> tuple[str, str]:
    html = build_email(
        title="API key rotated successfully",
        subtitle=f"Key: {key_name}",
        body_html=f"Your API key '{key_name}' has been rotated. The old key has been revoked. Update any integrations using this key.",
        cta_text="Manage API Keys",
        cta_url=f"{_APP_URL}/api-keys",
    )
    text = build_email_text("API key rotated successfully", f"API key '{key_name}' rotated. Old key revoked.", "Manage API Keys", f"{_APP_URL}/api-keys")
    return html, text


def build_api_key_revoked(key_name: str) -> tuple[str, str]:
    html = build_email(
        title="API key revoked",
        subtitle=f"Key: {key_name}",
        body_html=f"Your API key '{key_name}' has been revoked and can no longer be used.",
        cta_text="Manage API Keys",
        cta_url=f"{_APP_URL}/api-keys",
    )
    text = build_email_text("API key revoked", f"API key '{key_name}' has been revoked.", "Manage API Keys", f"{_APP_URL}/api-keys")
    return html, text


def build_api_abuse_detected(api_key_name: str) -> tuple[str, str]:
    html = build_email(
        title="Unusual API activity detected",
        subtitle=f"Key: {api_key_name}",
        body_html="We detected unusual activity on your API key. Please review your usage and rotate the key if you suspect abuse.",
        cta_text="Review Usage",
        cta_url=f"{_APP_URL}/api-keys",
    )
    text = build_email_text("Unusual API activity detected", f"Unusual activity on API key '{api_key_name}'. Review at: {_APP_URL}/api-keys", "Review Usage", f"{_APP_URL}/api-keys")
    return html, text


def build_wallet_success(amount: str, currency: str, balance: str | None) -> tuple[str, str]:
    balance_text = f" New balance: {balance} {currency}." if balance else ""
    html = build_email(
        title="Wallet top-up successful",
        subtitle=f"{amount} {currency}",
        body_html=f"Your wallet has been credited with {amount} {currency}.{balance_text}",
        cta_text="View Wallet",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Wallet top-up successful", f"Wallet credited with {amount} {currency}.{balance_text}", "View Wallet", f"{_APP_URL}/billing")
    return html, text


def build_wallet_failed(amount: str, currency: str, reason: str | None) -> tuple[str, str]:
    err = f" Reason: {reason}" if reason else ""
    html = build_email(
        title="Wallet top-up failed",
        subtitle=f"{amount} {currency}",
        body_html=f"Your payment of {amount} {currency} could not be processed.{err} Please check your payment method and try again.",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Wallet top-up failed", f"Payment of {amount} {currency} failed.{err}", "View Billing", f"{_APP_URL}/billing")
    return html, text


def build_low_balance(balance: str, currency: str) -> tuple[str, str]:
    html = build_email(
        title="Low wallet balance",
        subtitle=f"Balance: {balance} {currency}",
        body_html=f"Your wallet balance is low ({balance} {currency}). Consider adding funds to avoid service interruptions.",
        cta_text="Add Funds",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Low wallet balance", f"Wallet balance is low: {balance} {currency}. Add funds at: {_APP_URL}/billing", "Add Funds", f"{_APP_URL}/billing")
    return html, text


def build_usage_summary(period: str, total_cost: str, currency: str, requests: int) -> tuple[str, str]:
    html = build_email(
        title="Monthly usage summary",
        subtitle=period,
        body_html=f"Total usage: {requests} requests<br>Total cost: {total_cost} {currency}<br><br>Thank you for using Zyntra.",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Monthly usage summary", f"Period: {period}\nTotal: {requests} requests\nCost: {total_cost} {currency}", "View Billing", f"{_APP_URL}/billing")
    return html, text


def build_invoice_available(invoice_number: str) -> tuple[str, str]:
    html = build_email(
        title="Invoice available",
        subtitle=f"Invoice #{invoice_number}",
        body_html="A new invoice has been generated and is available for download.",
        cta_text="View Invoice",
        cta_url=f"{_APP_URL}/billing/invoices",
    )
    text = build_email_text("Invoice available", f"Invoice #{invoice_number} is available.", "View Invoice", f"{_APP_URL}/billing/invoices")
    return html, text


def build_suspicious_login(user_name: str | None, ip_address: str | None, location: str | None) -> tuple[str, str]:
    display = user_name or "someone"
    ip = ip_address or "an unknown IP"
    loc = f" from {location}" if location else ""
    html = build_email(
        title="Suspicious login detected",
        subtitle=f"Hello {display},",
        body_html=f"We detected a login from {ip}{loc}. If this was you, no action is needed. If this wasn't you, please secure your account immediately.",
        cta_text="Secure Account",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Suspicious login detected", f"Login from {ip}{loc}. If this wasn't you, secure your account: {_APP_URL}/settings/security", "Secure Account", f"{_APP_URL}/settings/security")
    return html, text


def build_security_alert(title: str, description: str | None) -> tuple[str, str]:
    desc = description or "A security event has been detected. Please review the admin dashboard."
    html = build_email(
        title="Security alert",
        subtitle=title,
        body_html=desc,
        cta_text="View Security Dashboard",
        cta_url=f"{_APP_URL}/admin/security",
    )
    text = build_email_text("Security alert", f"{title}\n{desc}", "View Security Dashboard", f"{_APP_URL}/admin/security")
    return html, text


def build_mfa_enabled() -> tuple[str, str]:
    html = build_email(
        title="Two-factor authentication enabled",
        subtitle="Security",
        body_html="Two-factor authentication has been successfully enabled on your account. Your account is now more secure.",
        cta_text="View Security Settings",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Two-factor authentication enabled", "2FA has been enabled on your account.", "View Security Settings", f"{_APP_URL}/settings/security")
    return html, text


def build_mfa_disabled() -> tuple[str, str]:
    html = build_email(
        title="Two-factor authentication disabled",
        subtitle="Security",
        body_html="Two-factor authentication has been disabled on your account. We recommend re-enabling it for better security.",
        cta_text="View Security Settings",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Two-factor authentication disabled", "2FA has been disabled on your account.", "View Security Settings", f"{_APP_URL}/settings/security")
    return html, text


def build_password_changed(user_name: str | None = None) -> tuple[str, str]:
    display = user_name or "there"
    html = build_email(
        title="Password changed successfully",
        subtitle=f"Hi {display},",
        body_html="Your password has been successfully changed.",
        cta_text="View Security Settings",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Password changed successfully", "Your password has been changed.", "View Security Settings", f"{_APP_URL}/settings/security")
    return html, text


def build_email_verified() -> tuple[str, str]:
    html = build_email(
        title="Email verified",
        subtitle="Account",
        body_html="Your email address has been successfully verified. Your account is now fully active.",
        cta_text="Go to Dashboard",
        cta_url=f"{_APP_URL}/dashboard",
    )
    text = build_email_text("Email verified", "Your email address has been verified. Your account is now fully active.", "Go to Dashboard", f"{_APP_URL}/dashboard")
    return html, text


def build_new_feature(title: str, description: str | None) -> tuple[str, str]:
    html = build_email(
        title=f"New feature available: {title}",
        subtitle="Product Update",
        body_html=description or "We've launched a new feature on Zyntra. Check it out!",
        cta_text="Learn More",
        cta_url=f"{_APP_URL}/changelog",
    )
    text = build_email_text(f"New feature: {title}", description or "New feature launched on Zyntra!", "Learn More", f"{_APP_URL}/changelog")
    return html, text


def build_zyntry_beta_invitation(
    access_date: str,
    recipient_name: str | None = None,
    app_url: str | None = None,
    credit_amount: str = "$5.00",
) -> tuple[str, str]:
    """Build the first beta group access message using email safe markup."""
    name = escape(recipient_name.strip()) if recipient_name else "there"
    date = escape(access_date.strip())
    credit = escape(credit_amount.strip())
    destination = escape((app_url or _APP_URL).rstrip("/"), quote=True)

    html = f'''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Welcome to the Zyntry beta</title></head>
<body style="margin:0;padding:0;background:#070b18;font-family:Arial,Helvetica,sans-serif;color:#e8ecff;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#070b18;"><tr><td align="center" style="padding:36px 16px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;background:#10172a;border:1px solid #273252;border-radius:24px;overflow:hidden;">
<tr><td style="padding:42px 38px 34px;background:#5b21b6;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
<td style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-.4px;">Zyntry</td>
<td align="right"><span style="display:inline-block;padding:7px 12px;border:1px solid #c4b5fd;border-radius:999px;color:#fff;font-size:11px;font-weight:700;letter-spacing:1.3px;">EARLY ACCESS</span></td>
</tr></table>
<div style="font-size:46px;line-height:1;margin:38px 0 20px;">&#10024;</div>
<h1 style="margin:0;color:#fff;font-size:34px;line-height:1.14;letter-spacing:-1px;">Your Zyntry beta access is ready.</h1>
<p style="margin:16px 0 0;color:#ede9fe;font-size:16px;line-height:1.65;">You are part of the first group helping us test and improve Zyntry.</p>
</td></tr>
<tr><td style="padding:38px;">
<p style="margin:0 0 18px;color:#fff;font-size:17px;">Hey {name},</p>
<p style="margin:0 0 28px;color:#b9c2dd;font-size:15px;line-height:1.75;">Your account has been selected for early access. We have also added testing credit to your wallet so you can explore the available features.</p>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 30px;background:#161f36;border:1px solid #303d60;border-radius:16px;"><tr>
<td width="58" valign="top" style="padding:22px 0 22px 22px;font-size:26px;">&#128176;</td>
<td style="padding:20px 22px 20px 10px;"><div style="color:#8b9ac4;font-size:11px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;">Testing credit added</div>
<div style="margin-top:7px;color:#fff;font-size:22px;font-weight:700;line-height:1.45;">{credit} is now in your wallet</div>
<div style="margin-top:6px;color:#aeb9d7;font-size:13px;line-height:1.55;">Sign in {date} and use this credit while testing Zyntry. This credit is intended for beta testing.</div></td>
</tr></table>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom:30px;"><tr>
<td width="33%" valign="top" style="padding-right:8px;"><div style="color:#a78bfa;font-size:18px;font-weight:800;">01</div><div style="margin-top:7px;color:#fff;font-size:13px;font-weight:700;">Explore early</div></td>
<td width="33%" valign="top" style="padding:0 8px;"><div style="color:#60a5fa;font-size:18px;font-weight:800;">02</div><div style="margin-top:7px;color:#fff;font-size:13px;font-weight:700;">Test freely</div></td>
<td width="33%" valign="top" style="padding-left:8px;"><div style="color:#34d399;font-size:18px;font-weight:800;">03</div><div style="margin-top:7px;color:#fff;font-size:13px;font-weight:700;">Shape Zyntry</div></td>
</tr></table>
<table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center"><tr><td align="center" bgcolor="#7c3aed" style="border-radius:12px;"><a href="{destination}" style="display:inline-block;padding:15px 28px;color:#fff;text-decoration:none;font-size:14px;font-weight:800;">Open Zyntry&nbsp;&nbsp;&rarr;</a></td></tr></table>
<p style="margin:30px 0 0;text-align:center;color:#7784a8;font-size:12px;line-height:1.6;">Early builds may change while you test. Your feedback will directly influence what ships.</p>
</td></tr>
<tr><td style="padding:22px 38px;background:#0c1222;border-top:1px solid #252f4c;text-align:center;color:#697797;font-size:11px;line-height:1.6;">You received this because you were selected for the Zyntry founding beta.<br>&copy; 2026 Zyntry. Build what comes next.</td></tr>
</table></td></tr></table>
</body></html>'''

    text = build_email_text(
        "Your Zyntry beta access is ready",
        (
            f"Hey {recipient_name.strip() if recipient_name else 'there'},\n\n"
            "You are part of Zyntry's first beta testing group. "
            f"We added {credit_amount.strip()} in testing credit to your wallet. "
            f"Sign in {access_date.strip()} to begin testing. "
            "Your feedback will help us improve Zyntry."
        ),
        "Open Zyntry",
        app_url or _APP_URL,
    )
    return html, text


def build_fix_notification(title: str, description: str | None) -> tuple[str, str]:
    html = build_email(
        title=f"We've fixed an issue: {title}",
        subtitle="Product Update",
        body_html=description or "We've resolved an issue affecting your account. No action is needed.",
        cta_text="Learn More",
        cta_url=f"{_APP_URL}/changelog",
    )
    text = build_email_text(f"Issue fixed: {title}", description or "An issue has been resolved. No action needed.", "Learn More", f"{_APP_URL}/changelog")
    return html, text


def build_maintenance_notice(start_time: str, end_time: str | None, description: str | None) -> tuple[str, str]:
    end = f" to {end_time}" if end_time else ""
    html = build_email(
        title="Scheduled maintenance notice",
        subtitle=f"On {start_time}{end}",
        body_html=description or "We'll be performing scheduled maintenance on the platform. Some features may be temporarily unavailable.",
        cta_text="View Status",
        cta_url=f"{_APP_URL}/status",
    )
    text = build_email_text("Scheduled maintenance notice", f"Maintenance: {start_time}{end}\n{description or 'Some features may be temporarily unavailable.'}", "View Status", f"{_APP_URL}/status")
    return html, text


def build_status_update(title: str, description: str | None) -> tuple[str, str]:
    html = build_email(
        title=f"Platform status update: {title}",
        subtitle="Status",
        body_html=description or "We're providing an update on the platform status.",
        cta_text="View Status",
        cta_url=f"{_APP_URL}/status",
    )
    text = build_email_text(f"Platform status update: {title}", description or "Platform status update.", "View Status", f"{_APP_URL}/status")
    return html, text


def build_support_received(ticket_id: str) -> tuple[str, str]:
    html = build_email(
        title="Support request received",
        subtitle=f"Ticket #{ticket_id}",
        body_html=f"We've received your support request (ticket #{ticket_id}) and a team member will respond shortly.",
        cta_text="View Ticket",
        cta_url=f"{_APP_URL}/support/tickets/{ticket_id}",
    )
    text = build_email_text("Support request received", f"We've received your support request (ticket #{ticket_id}). A team member will respond shortly.", "View Ticket", f"{_APP_URL}/support/tickets/{ticket_id}")
    return html, text


def build_support_updated(ticket_id: str) -> tuple[str, str]:
    html = build_email(
        title="Support ticket updated",
        subtitle=f"Ticket #{ticket_id}",
        body_html=f"Your support ticket (ticket #{ticket_id}) has been updated. Please check for a response.",
        cta_text="View Ticket",
        cta_url=f"{_APP_URL}/support/tickets/{ticket_id}",
    )
    text = build_email_text("Support ticket updated", f"Your support ticket (ticket #{ticket_id}) has been updated.", "View Ticket", f"{_APP_URL}/support/tickets/{ticket_id}")
    return html, text


def build_support_resolved(ticket_id: str) -> tuple[str, str]:
    html = build_email(
        title="Support request resolved",
        subtitle=f"Ticket #{ticket_id}",
        body_html=f"Your support ticket (ticket #{ticket_id}) has been resolved. If you have any further questions, feel free to reply.",
        cta_text="View Ticket",
        cta_url=f"{_APP_URL}/support/tickets/{ticket_id}",
    )
    text = build_email_text("Support request resolved", f"Your support ticket (ticket #{ticket_id}) has been resolved.", "View Ticket", f"{_APP_URL}/support/tickets/{ticket_id}")
    return html, text


def build_login_verification_code(code: str) -> tuple[str, str]:
    html = build_email(
        title="Login verification code",
        subtitle="Verify your identity",
        body_html=f"Your login verification code is: <strong>{code}</strong>. This code expires in 10 minutes.",
        cta_text="Go to Login",
        cta_url=f"{_APP_URL}/login",
    )
    text = build_email_text("Login verification code", f"Your login verification code is: {code}\n\nThis code expires in 10 minutes.\n\n{_APP_URL}/login", "Go to Login", f"{_APP_URL}/login")
    return html, text


def build_magic_login_link(token: str) -> tuple[str, str]:
    html = build_email(
        title="Magic login link",
        subtitle="Sign in without a password",
        body_html="Click the button below to sign in to your Zyntra account. This link expires in 15 minutes and can only be used once.",
        cta_text="Sign In",
        cta_url=f"{_APP_URL}/auth/magic?token={token}",
    )
    text = build_email_text("Magic login link", f"Sign in with this link: {_APP_URL}/auth/magic?token={token}\n\nThis link expires in 15 minutes.", "Sign In", f"{_APP_URL}/auth/magic?token={token}")
    return html, text


def build_email_changed(new_email: str) -> tuple[str, str]:
    html = build_email(
        title="Email address changed",
        subtitle="Account",
        body_html=f"Your email address has been changed to <strong>{new_email}</strong>. If you didn't make this change, please secure your account immediately.",
        cta_text="Secure Account",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Email address changed", f"Your email address has been changed to {new_email}.\n\nIf you didn't make this change, secure your account: {_APP_URL}/settings/security", "Secure Account", f"{_APP_URL}/settings/security")
    return html, text


def build_account_deletion_confirmation() -> tuple[str, str]:
    html = build_email(
        title="Account deletion confirmation",
        subtitle="Account",
        body_html="Your account deletion has been requested. All your data will be permanently deleted within 30 days. You can cancel this request within 7 days by signing in to your account.",
        cta_text="Cancel Deletion",
        cta_url=f"{_APP_URL}/settings/account",
    )
    text = build_email_text("Account deletion confirmation", "Your account deletion has been requested. All data will be permanently deleted within 30 days. Cancel within 7 days at: {_APP_URL}/settings/account", "Cancel Deletion", f"{_APP_URL}/settings/account")
    return html, text


def build_api_key_expired(key_name: str) -> tuple[str, str]:
    html = build_email(
        title="API key expired",
        subtitle=f"Key: {key_name}",
        body_html=f"Your API key '{key_name}' has expired and can no longer be used. Please rotate or create a new key.",
        cta_text="Manage API Keys",
        cta_url=f"{_APP_URL}/api-keys",
    )
    text = build_email_text("API key expired", f"API key '{key_name}' has expired.", "Manage API Keys", f"{_APP_URL}/api-keys")
    return html, text


def build_provider_disconnected(provider: str, display_name: str | None = None) -> tuple[str, str]:
    name = display_name or provider
    html = build_email(
        title=f"{provider} disconnected",
        subtitle=f"Connection removed",
        body_html=f"The {provider} connection '{name}' has been disconnected and will no longer be used for actions or syncing.",
        cta_text="Reconnect",
        cta_url=f"{_APP_URL}/tools",
    )
    text = build_email_text(f"{provider} disconnected", f"The {provider} connection '{name}' has been disconnected.", "Reconnect", f"{_APP_URL}/tools")
    return html, text


def build_provider_token_expired(provider: str, display_name: str | None = None) -> tuple[str, str]:
    name = display_name or provider
    html = build_email(
        title=f"{provider} token expired",
        subtitle=f"Reconnection required",
        body_html=f"The access token for {provider} connection '{name}' has expired. Please re-authenticate to continue using this integration.",
        cta_text="Reconnect",
        cta_url=f"{_APP_URL}/tools",
    )
    text = build_email_text(f"{provider} token expired", f"Access token for {provider} connection '{name}' has expired. Re-authenticate at: {_APP_URL}/tools", "Reconnect", f"{_APP_URL}/tools")
    return html, text


def build_provider_reconnect_required(provider: str, display_name: str | None = None) -> tuple[str, str]:
    name = display_name or provider
    html = build_email(
        title=f"{provider} reconnection required",
        subtitle=f"Action needed",
        body_html=f"The {provider} connection '{name}' requires re-authentication. Please reconnect to continue using this integration.",
        cta_text="Reconnect",
        cta_url=f"{_APP_URL}/tools",
    )
    text = build_email_text(f"{provider} reconnection required", f"{provider} connection '{name}' requires re-authentication. Reconnect at: {_APP_URL}/tools", "Reconnect", f"{_APP_URL}/tools")
    return html, text


def build_runtime_rebuild_started(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime rebuild started",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime rebuild has started. You'll receive another notification when it's complete.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime rebuild started", f"Runtime '{runtime_name}' rebuild has started.", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


def build_runtime_rebuild_completed(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime rebuild completed",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime has been successfully rebuilt and is now active.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime rebuild completed", f"Runtime '{runtime_name}' has been rebuilt successfully.", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


def build_runtime_unhealthy(runtime_name: str, reason: str | None = None) -> tuple[str, str]:
    err = f" Reason: {reason}" if reason else ""
    html = build_email(
        title="Runtime unhealthy",
        subtitle=f"Runtime '{runtime_name}'",
        body_html=f"Your runtime is currently unhealthy and may not be responding to requests.{err}",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime unhealthy", f"Runtime '{runtime_name}' is unhealthy.{err}", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


def build_runtime_recovered(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime recovered",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime has recovered and is now healthy and responding to requests.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime recovered", f"Runtime '{runtime_name}' has recovered.", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


def build_knowledge_sync_started(source_name: str) -> tuple[str, str]:
    html = build_email(
        title="Knowledge sync started",
        subtitle=f"Source '{source_name}'",
        body_html="The knowledge source synchronization has started. You'll receive another notification when it's complete.",
        cta_text="View Source",
        cta_url=f"{_APP_URL}/sources",
    )
    text = build_email_text("Knowledge sync started", f"Source '{source_name}' sync has started.", "View Source", f"{_APP_URL}/sources")
    return html, text


def build_source_connected(provider: str, source_name: str | None = None) -> tuple[str, str]:
    display = source_name or provider
    html = build_email(
        title=f"{provider} connected successfully",
        subtitle=f"Source '{display}'",
        body_html=f"The {provider} source has been successfully connected and will begin syncing your data.",
        cta_text="View Source",
        cta_url=f"{_APP_URL}/sources",
    )
    text = build_email_text(f"{provider} connected successfully", f"Source '{display}' connected. Syncing will begin automatically.", "View Source", f"{_APP_URL}/sources")
    return html, text


def build_source_disconnected(provider: str, source_name: str | None = None) -> tuple[str, str]:
    name = source_name or provider
    html = build_email(
        title=f"{provider} disconnected",
        subtitle=f"Source '{name}'",
        body_html=f"The {provider} source '{name}' has been disconnected and will no longer sync data.",
        cta_text="Reconnect Source",
        cta_url=f"{_APP_URL}/sources",
    )
    text = build_email_text(f"{provider} disconnected", f"Source '{name}' disconnected.", "Reconnect Source", f"{_APP_URL}/sources")
    return html, text


def build_credits_purchased(amount: str, currency: str, balance: str | None = None) -> tuple[str, str]:
    balance_text = f" New balance: {balance} {currency}." if balance else ""
    html = build_email(
        title="Credits purchased",
        subtitle=f"{amount} {currency}",
        body_html=f"Your account has been credited with {amount} {currency}.{balance_text}",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Credits purchased", f"Credits purchased: {amount} {currency}.{balance_text}", "View Billing", f"{_APP_URL}/billing")
    return html, text


def build_credits_running_low(
    balance: str,
    currency: str = "USD",
    threshold: str | None = None,
) -> tuple[str, str]:
    threshold_text = f" Your configured threshold is {threshold}." if threshold else ""
    html = build_email(
        title="Credits running low",
        subtitle=f"Balance: {balance} {currency}",
        body_html=(
            f"Your credit balance is low ({balance} {currency}).{threshold_text} "
            "Add funds soon to avoid service interruptions."
        ),
        cta_text="Add Funds",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text(
        "Credits running low",
        f"Credit balance is low: {balance} {currency}.{threshold_text} Add funds at: {_APP_URL}/billing",
        "Add Funds",
        f"{_APP_URL}/billing",
    )
    return html, text


def build_credits_exhausted() -> tuple[str, str]:
    html = build_email(
        title="Credits exhausted",
        subtitle="Account suspended",
        body_html="Your credit balance has been exhausted. Some services may be temporarily unavailable. Please add funds to restore full access.",
        cta_text="Add Funds",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Credits exhausted", "Your credit balance has been exhausted. Add funds to restore full access.", "Add Funds", f"{_APP_URL}/billing")
    return html, text


def build_payment_successful(amount: str, currency: str, invoice_url: str | None = None) -> tuple[str, str]:
    invoice_text = f" View invoice: {invoice_url}" if invoice_url else ""
    html = build_email(
        title="Payment successful",
        subtitle=f"{amount} {currency}",
        body_html=f"Your payment of {amount} {currency} was processed successfully.{invoice_text}",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Payment successful", f"Payment of {amount} {currency} was successful.{invoice_text}", "View Billing", f"{_APP_URL}/billing")
    return html, text


def build_payment_failed(amount: str, currency: str, reason: str | None = None) -> tuple[str, str]:
    err = f" Reason: {reason}" if reason else ""
    html = build_email(
        title="Payment failed",
        subtitle=f"{amount} {currency}",
        body_html=f"Your payment of {amount} {currency} could not be processed.{err} Please check your payment method and try again.",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Payment failed", f"Payment of {amount} {currency} failed.{err}", "View Billing", f"{_APP_URL}/billing")
    return html, text


def build_subscription_created(plan_name: str) -> tuple[str, str]:
    html = build_email(
        title="Subscription created",
        subtitle=f"Plan: {plan_name}",
        body_html=f"Your subscription to the {plan_name} plan has been successfully created.",
        cta_text="Manage Subscription",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Subscription created", f"Subscription to {plan_name} created.", "Manage Subscription", f"{_APP_URL}/billing")
    return html, text


def build_subscription_renewed(plan_name: str) -> tuple[str, str]:
    html = build_email(
        title="Subscription renewed",
        subtitle=f"Plan: {plan_name}",
        body_html=f"Your subscription to the {plan_name} plan has been renewed.",
        cta_text="Manage Subscription",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Subscription renewed", f"Subscription to {plan_name} renewed.", "Manage Subscription", f"{_APP_URL}/billing")
    return html, text


def build_subscription_canceled(plan_name: str) -> tuple[str, str]:
    html = build_email(
        title="Subscription canceled",
        subtitle=f"Plan: {plan_name}",
        body_html=f"Your subscription to the {plan_name} plan has been canceled. You will continue to have access until the end of your billing period.",
        cta_text="Manage Subscription",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Subscription canceled", f"Subscription to {plan_name} canceled. Access continues until end of billing period.", "Manage Subscription", f"{_APP_URL}/billing")
    return html, text


def build_refund_processed(amount: str, currency: str) -> tuple[str, str]:
    html = build_email(
        title="Refund processed",
        subtitle=f"{amount} {currency}",
        body_html=f"A refund of {amount} {currency} has been processed to your original payment method. Please allow 5-10 business days for it to appear.",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Refund processed", f"Refund of {amount} {currency} processed. Allow 5-10 business days.", "View Billing", f"{_APP_URL}/billing")
    return html, text


def build_deployment_started(deployment_name: str, environment: str | None = None) -> tuple[str, str]:
    env = f" ({environment})" if environment else ""
    html = build_email(
        title="Deployment started",
        subtitle=f"Deployment '{deployment_name}'{env}",
        body_html="Your deployment has started. You'll receive another notification when it's complete.",
        cta_text="View Deployment",
        cta_url=f"{_APP_URL}/deployments",
    )
    text = build_email_text("Deployment started", f"Deployment '{deployment_name}'{env} started.", "View Deployment", f"{_APP_URL}/deployments")
    return html, text


def build_deployment_succeeded(deployment_name: str, environment: str | None = None) -> tuple[str, str]:
    env = f" ({environment})" if environment else ""
    html = build_email(
        title="Deployment succeeded",
        subtitle=f"Deployment '{deployment_name}'{env}",
        body_html="Your deployment has completed successfully.",
        cta_text="View Deployment",
        cta_url=f"{_APP_URL}/deployments",
    )
    text = build_email_text("Deployment succeeded", f"Deployment '{deployment_name}'{env} succeeded.", "View Deployment", f"{_APP_URL}/deployments")
    return html, text


def build_deployment_failed(deployment_name: str, error: str | None = None, environment: str | None = None) -> tuple[str, str]:
    env = f" ({environment})" if environment else ""
    err = f" Error: {error}" if error else ""
    html = build_email(
        title="Deployment failed",
        subtitle=f"Deployment '{deployment_name}'{env}",
        body_html=f"Your deployment could not be completed.{err}",
        cta_text="View Deployment",
        cta_url=f"{_APP_URL}/deployments",
    )
    text = build_email_text("Deployment failed", f"Deployment '{deployment_name}'{env} failed.{err}", "View Deployment", f"{_APP_URL}/deployments")
    return html, text


def build_deployment_rolled_back(deployment_name: str, environment: str | None = None) -> tuple[str, str]:
    env = f" ({environment})" if environment else ""
    html = build_email(
        title="Deployment rolled back",
        subtitle=f"Deployment '{deployment_name}'{env}",
        body_html="Your deployment has been rolled back to the previous stable version.",
        cta_text="View Deployment",
        cta_url=f"{_APP_URL}/deployments",
    )
    text = build_email_text("Deployment rolled back", f"Deployment '{deployment_name}'{env} rolled back.", "View Deployment", f"{_APP_URL}/deployments")
    return html, text


def build_workflow_completed(workflow_name: str) -> tuple[str, str]:
    html = build_email(
        title="Workflow completed",
        subtitle=f"Workflow '{workflow_name}'",
        body_html="Your workflow has completed successfully.",
        cta_text="View Workflow",
        cta_url=f"{_APP_URL}/workflows",
    )
    text = build_email_text("Workflow completed", f"Workflow '{workflow_name}' completed.", "View Workflow", f"{_APP_URL}/workflows")
    return html, text


def build_workflow_failed(workflow_name: str, error: str | None = None) -> tuple[str, str]:
    err = f" Error: {error}" if error else ""
    html = build_email(
        title="Workflow failed",
        subtitle=f"Workflow '{workflow_name}'",
        body_html=f"Your workflow could not be completed.{err}",
        cta_text="View Workflow",
        cta_url=f"{_APP_URL}/workflows",
    )
    text = build_email_text("Workflow failed", f"Workflow '{workflow_name}' failed.{err}", "View Workflow", f"{_APP_URL}/workflows")
    return html, text


def build_workflow_waiting_approval(workflow_name: str, step: str | None = None) -> tuple[str, str]:
    step_text = f" Step: {step}." if step else ""
    html = build_email(
        title="Workflow waiting for approval",
        subtitle=f"Workflow '{workflow_name}'",
        body_html=f"Your workflow is waiting for approval.{step_text} Please review and approve the pending action to continue.",
        cta_text="Review Approval",
        cta_url=f"{_APP_URL}/workflows",
    )
    text = build_email_text("Workflow waiting for approval", f"Workflow '{workflow_name}' waiting for approval.{step_text} Review at: {_APP_URL}/workflows", "Review Approval", f"{_APP_URL}/workflows")
    return html, text


def build_dangerous_action_confirmation(action_name: str, provider: str) -> tuple[str, str]:
    html = build_email(
        title="Dangerous action requires confirmation",
        subtitle=f"{provider} action",
        body_html=f"A potentially dangerous action '{action_name}' is pending your confirmation on {provider}. Please review and approve or reject it.",
        cta_text="Review Action",
        cta_url=f"{_APP_URL}/actions/confirmations",
    )
    text = build_email_text("Dangerous action requires confirmation", f"Action '{action_name}' on {provider} requires confirmation. Review at: {_APP_URL}/actions/confirmations", "Review Action", f"{_APP_URL}/actions/confirmations")
    return html, text


def build_scheduled_workflow_executed(workflow_name: str) -> tuple[str, str]:
    html = build_email(
        title="Scheduled workflow executed",
        subtitle=f"Workflow '{workflow_name}'",
        body_html="Your scheduled workflow has been executed successfully.",
        cta_text="View Workflow",
        cta_url=f"{_APP_URL}/workflows",
    )
    text = build_email_text("Scheduled workflow executed", f"Scheduled workflow '{workflow_name}' executed.", "View Workflow", f"{_APP_URL}/workflows")
    return html, text


def build_scheduled_workflow_failed(workflow_name: str, error: str | None = None) -> tuple[str, str]:
    err = f" Error: {error}" if error else ""
    html = build_email(
        title="Scheduled workflow failed",
        subtitle=f"Workflow '{workflow_name}'",
        body_html=f"Your scheduled workflow could not be executed.{err}",
        cta_text="View Workflow",
        cta_url=f"{_APP_URL}/workflows",
    )
    text = build_email_text("Scheduled workflow failed", f"Scheduled workflow '{workflow_name}' failed.{err}", "View Workflow", f"{_APP_URL}/workflows")
    return html, text


def build_new_login_detected(device: str | None, location: str | None, ip_address: str | None) -> tuple[str, str]:
    device_text = f" from {device}" if device else ""
    location_text = f" in {location}" if location else ""
    ip_text = f" (IP: {ip_address})" if ip_address else ""
    html = build_email(
        title="New login detected",
        subtitle="Security",
        body_html=f"A new login was detected{device_text}{location_text}{ip_text}. If this was you, no action is needed.",
        cta_text="View Security Settings",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("New login detected", f"New login detected{device_text}{location_text}{ip_text}. If this wasn't you, secure your account: {_APP_URL}/settings/security", "View Security Settings", f"{_APP_URL}/settings/security")
    return html, text


def build_login_from_new_device(device: str, location: str | None, ip_address: str | None) -> tuple[str, str]:
    loc = f" from {location}" if location else ""
    ip = f" (IP: {ip_address})" if ip_address else ""
    html = build_email(
        title="Login from new device",
        subtitle="Security",
        body_html=f"A login was detected from a new device: <strong>{device}</strong>{loc}{ip}. If this was you, no action is needed.",
        cta_text="View Security Settings",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Login from new device", f"Login from new device: {device}{loc}{ip}. If this wasn't you, secure your account: {_APP_URL}/settings/security", "View Security Settings", f"{_APP_URL}/settings/security")
    return html, text


def build_login_from_new_country(country: str, ip_address: str | None) -> tuple[str, str]:
    ip = f" (IP: {ip_address})" if ip_address else ""
    html = build_email(
        title="Login from new country",
        subtitle="Security",
        body_html=f"A login was detected from a new country: <strong>{country}</strong>{ip}. If this was you, no action is needed.",
        cta_text="View Security Settings",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Login from new country", f"Login from new country: {country}{ip}. If this wasn't you, secure your account: {_APP_URL}/settings/security", "View Security Settings", f"{_APP_URL}/settings/security")
    return html, text


def build_recovery_codes_regenerated() -> tuple[str, str]:
    html = build_email(
        title="Recovery codes regenerated",
        subtitle="Security",
        body_html="Your two-factor authentication recovery codes have been regenerated. Your old codes are now invalid.",
        cta_text="View Security Settings",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Recovery codes regenerated", "Your 2FA recovery codes have been regenerated. Old codes are now invalid.", "View Security Settings", f"{_APP_URL}/settings/security")
    return html, text


def build_oauth_permission_changed(provider: str, permissions: list[str]) -> tuple[str, str]:
    perms = ", ".join(permissions)
    html = build_email(
        title="OAuth permissions changed",
        subtitle=f"{provider} integration",
        body_html=f"The permissions for your {provider} integration have been changed. New permissions: {perms}.",
        cta_text="Manage Integrations",
        cta_url=f"{_APP_URL}/tools",
    )
    text = build_email_text("OAuth permissions changed", f"{provider} integration permissions changed: {perms}. Manage at: {_APP_URL}/tools", "Manage Integrations", f"{_APP_URL}/tools")
    return html, text


def build_weekly_usage_summary(period: str, total_cost: str, currency: str, requests: int) -> tuple[str, str]:
    html = build_email(
        title="Weekly usage summary",
        subtitle=period,
        body_html=f"Total usage: {requests} requests<br>Total cost: {total_cost} {currency}<br><br>Thank you for using Zyntra.",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("Weekly usage summary", f"Period: {period}\nTotal: {requests} requests\nCost: {total_cost} {currency}", "View Billing", f"{_APP_URL}/billing")
    return html, text


def build_incident_notification(incident_name: str, description: str | None = None) -> tuple[str, str]:
    desc = description or "We are currently investigating an incident that may affect service availability."
    html = build_email(
        title="Incident notification",
        subtitle=incident_name,
        body_html=f"We are currently investigating an incident: {incident_name}. {desc}",
        cta_text="View Status",
        cta_url=f"{_APP_URL}/status",
    )
    text = build_email_text("Incident notification", f"Incident: {incident_name}\n{desc}\n\nView status: {_APP_URL}/status", "View Status", f"{_APP_URL}/status")
    return html, text


def build_service_restored(service_name: str) -> tuple[str, str]:
    html = build_email(
        title="Service restored",
        subtitle=service_name,
        body_html=f"The {service_name} service has been restored and is now operating normally.",
        cta_text="View Status",
        cta_url=f"{_APP_URL}/status",
    )
    text = build_email_text("Service restored", f"{service_name} service has been restored.", "View Status", f"{_APP_URL}/status")
    return html, text


def build_new_user_registered(user_email: str, user_name: str | None = None) -> tuple[str, str]:
    name = user_name or user_email
    html = build_email(
        title="New user registered",
        subtitle=f"User: {name}",
        body_html=f"A new user has registered: {name} ({user_email}).",
        cta_text="View Users",
        cta_url=f"{_APP_URL}/admin/users",
    )
    text = build_email_text("New user registered", f"New user registered: {name} ({user_email})", "View Users", f"{_APP_URL}/admin/users")
    return html, text


def build_new_organization_created(org_name: str, owner_email: str) -> tuple[str, str]:
    html = build_email(
        title="New organization created",
        subtitle=f"Organization: {org_name}",
        body_html=f"A new organization has been created: {org_name} (owner: {owner_email}).",
        cta_text="View Organizations",
        cta_url=f"{_APP_URL}/admin/organizations",
    )
    text = build_email_text("New organization created", f"New organization: {org_name} (owner: {owner_email})", "View Organizations", f"{_APP_URL}/admin/organizations")
    return html, text


def build_large_payment_received(amount: str, currency: str, payer_email: str) -> tuple[str, str]:
    html = build_email(
        title="Large payment received",
        subtitle=f"{amount} {currency}",
        body_html=f"A large payment of {amount} {currency} has been received from {payer_email}.",
        cta_text="View Billing",
        cta_url=f"{_APP_URL}/admin/billing",
    )
    text = build_email_text("Large payment received", f"Large payment: {amount} {currency} from {payer_email}", "View Billing", f"{_APP_URL}/admin/billing")
    return html, text


def build_runtime_repeatedly_failing(runtime_name: str, failure_count: int) -> tuple[str, str]:
    html = build_email(
        title="Runtime repeatedly failing",
        subtitle=f"Runtime '{runtime_name}'",
        body_html=f"Runtime '{runtime_name}' has failed {failure_count} times in a row. Please investigate the configuration and logs.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime repeatedly failing", f"Runtime '{runtime_name}' failed {failure_count} times.", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


def build_high_infrastructure_usage_alert(metric: str, value: str, threshold: str) -> tuple[str, str]:
    html = build_email(
        title="High infrastructure usage alert",
        subtitle=metric,
        body_html=f"Your {metric} usage has reached {value}, exceeding the threshold of {threshold}.",
        cta_text="View Usage",
        cta_url=f"{_APP_URL}/billing",
    )
    text = build_email_text("High infrastructure usage alert", f"{metric} usage: {value} (threshold: {threshold})", "View Usage", f"{_APP_URL}/billing")
    return html, text


def build_abuse_detected(abuse_type: str, details: str | None = None) -> tuple[str, str]:
    detail_text = f" Details: {details}" if details else ""
    html = build_email(
        title="Abuse detected",
        subtitle=abuse_type,
        body_html=f"Suspicious activity has been detected on your account: {abuse_type}.{detail_text} Please review your account activity.",
        cta_text="View Security",
        cta_url=f"{_APP_URL}/settings/security",
    )
    text = build_email_text("Abuse detected", f"Abuse detected: {abuse_type}.{detail_text} Review at: {_APP_URL}/settings/security", "View Security", f"{_APP_URL}/settings/security")
    return html, text


def build_support_ticket_created(ticket_id: str, subject: str) -> tuple[str, str]:
    html = build_email(
        title="Support ticket created",
        subtitle=f"Ticket #{ticket_id}",
        body_html=f"Your support ticket has been created: <strong>{subject}</strong>. A team member will respond shortly.",
        cta_text="View Ticket",
        cta_url=f"{_APP_URL}/support/tickets/{ticket_id}",
    )
    text = build_email_text("Support ticket created", f"Ticket #{ticket_id}: {subject}", "View Ticket", f"{_APP_URL}/support/tickets/{ticket_id}")
    return html, text


def build_runtime_build_started(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title="Runtime build started",
        subtitle=f"Runtime '{runtime_name}'",
        body_html="Your runtime build has started. You'll receive another notification when it's complete.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text("Runtime build started", f"Runtime '{runtime_name}' build has started.", "View Runtime", f"{_APP_URL}/runtimes")
    return html, text


EMAIL_TEMPLATES: dict[str, Any] = {
    "welcome": build_welcome_email,
    "verify_email": build_verify_email,
    "login_verification_code": build_login_verification_code,
    "magic_login_link": build_magic_login_link,
    "email_changed": build_email_changed,
    "account_deletion_confirmation": build_account_deletion_confirmation,
    "project_created": build_project_created,
    "email_verified": build_email_verified,
    "password_reset": build_password_reset,
    "password_changed": build_password_changed,
    "api_key_created": build_api_key_created,
    "api_key_rotated": build_api_key_rotated,
    "api_key_revoked": build_api_key_revoked,
    "api_key_expired": build_api_key_expired,
    "api_abuse_detected": build_api_abuse_detected,
    "github_connected": lambda name: build_source_connected("GitHub", name),
    "github_disconnected": lambda name: build_provider_disconnected("GitHub", name),
    "github_token_expired": lambda name: build_provider_token_expired("GitHub", name),
    "github_reconnect_required": lambda name: build_provider_reconnect_required("GitHub", name),
    "gitlab_connected": lambda name: build_source_connected("GitLab", name),
    "gitlab_disconnected": lambda name: build_provider_disconnected("GitLab", name),
    "gitlab_token_expired": lambda name: build_provider_token_expired("GitHub", name),
    "gitlab_reconnect_required": lambda name: build_provider_reconnect_required("GitLab", name),
    "slack_connected": lambda name: build_tool_connected("Slack"),
    "slack_disconnected": lambda name: build_provider_disconnected("Slack", name),
    "slack_token_expired": lambda name: build_provider_token_expired("Slack", name),
    "slack_reconnect_required": lambda name: build_provider_reconnect_required("Slack", name),
    "discord_connected": lambda name: build_tool_connected("Discord"),
    "discord_disconnected": lambda name: build_provider_disconnected("Discord", name),
    "discord_token_expired": lambda name: build_provider_token_expired("Discord", name),
    "discord_reconnect_required": lambda name: build_provider_reconnect_required("Discord", name),
    "notion_connected": lambda name: build_source_connected("Notion", name),
    "notion_disconnected": lambda name: build_provider_disconnected("Notion", name),
    "notion_token_expired": lambda name: build_provider_token_expired("Notion", name),
    "notion_reconnect_required": lambda name: build_provider_reconnect_required("Notion", name),
    "jira_connected": lambda name: build_source_connected("Jira", name),
    "jira_disconnected": lambda name: build_provider_disconnected("Jira", name),
    "jira_token_expired": lambda name: build_provider_token_expired("Jira", name),
    "jira_reconnect_required": lambda name: build_provider_reconnect_required("Jira", name),
    "railway_connected": lambda name: build_source_connected("Railway", name),
    "railway_disconnected": lambda name: build_provider_disconnected("Railway", name),
    "railway_token_expired": lambda name: build_provider_token_expired("Railway", name),
    "railway_reconnect_required": lambda name: build_provider_reconnect_required("Railway", name),
    "render_connected": lambda name: build_source_connected("Render", name),
    "render_disconnected": lambda name: build_provider_disconnected("Render", name),
    "render_token_expired": lambda name: build_provider_token_expired("Render", name),
    "render_reconnect_required": lambda name: build_provider_reconnect_required("Render", name),
    "vercel_connected": lambda name: build_source_connected("Vercel", name),
    "vercel_disconnected": lambda name: build_provider_disconnected("Vercel", name),
    "vercel_token_expired": lambda name: build_provider_token_expired("Vercel", name),
    "vercel_reconnect_required": lambda name: build_provider_reconnect_required("Vercel", name),
    "gmail_connected": lambda name: build_source_connected("Gmail", name),
    "gmail_disconnected": lambda name: build_provider_disconnected("Gmail", name),
    "gmail_token_expired": lambda name: build_provider_token_expired("Gmail", name),
    "gmail_reconnect_required": lambda name: build_provider_reconnect_required("Gmail", name),
    "outlook_connected": lambda name: build_source_connected("Outlook", name),
    "outlook_disconnected": lambda name: build_provider_disconnected("Outlook", name),
    "outlook_token_expired": lambda name: build_provider_token_expired("Outlook", name),
    "outlook_reconnect_required": lambda name: build_provider_reconnect_required("Outlook", name),
    "dropbox_connected": lambda name: build_source_connected("Dropbox", name),
    "dropbox_disconnected": lambda name: build_provider_disconnected("Dropbox", name),
    "dropbox_token_expired": lambda name: build_provider_token_expired("Dropbox", name),
    "dropbox_reconnect_required": lambda name: build_provider_reconnect_required("Dropbox", name),
    "google_drive_connected": lambda name: build_source_connected("Google Drive", name),
    "google_drive_disconnected": lambda name: build_provider_disconnected("Google Drive", name),
    "google_drive_token_expired": lambda name: build_provider_token_expired("Google Drive", name),
    "google_drive_reconnect_required": lambda name: build_provider_reconnect_required("Google Drive", name),
    "runtime_ready": build_runtime_ready,
    "runtime_build_started": build_runtime_build_started,
    "runtime_rebuild_started": build_runtime_rebuild_started,
    "runtime_rebuild_completed": build_runtime_rebuild_completed,
    "runtime_failed": build_runtime_failed,
    "runtime_sync_finished": build_runtime_sync_finished,
    "runtime_sync_failed": build_runtime_sync_failed,
    "runtime_paused": build_runtime_paused,
    "runtime_resumed": build_runtime_resumed,
    "runtime_unhealthy": build_runtime_unhealthy,
    "runtime_recovered": build_runtime_recovered,
    "runtime_deleted": build_runtime_deleted,
    "knowledge_sync_started": build_knowledge_sync_started,
    "source_sync_finished": build_source_sync_finished,
    "source_sync_failed": build_source_sync_failed,
    "source_connected": build_source_connected,
    "source_disconnected": build_source_disconnected,
    "source_reauth": build_source_reauth,
    "provider_connected": build_source_connected,
    "provider_disconnected": lambda provider, display_name=None, source_name=None: build_source_disconnected(
        provider, source_name or display_name
    ),
    "provider_token_expired": build_provider_token_expired,
    "provider_reconnect_required": build_provider_reconnect_required,
    "credits_purchased": build_credits_purchased,
    "credits_running_low": build_credits_running_low,
    "credits_exhausted": build_credits_exhausted,
    "wallet_success": build_wallet_success,
    "wallet_failed": build_wallet_failed,
    "low_balance": build_low_balance,
    "payment_successful": build_payment_successful,
    "payment_failed": build_payment_failed,
    "usage_summary": build_usage_summary,
    "weekly_usage_summary": build_weekly_usage_summary,
    "invoice_available": build_invoice_available,
    "subscription_created": build_subscription_created,
    "subscription_renewed": build_subscription_renewed,
    "subscription_canceled": build_subscription_canceled,
    "refund_processed": build_refund_processed,
    "deployment_started": build_deployment_started,
    "deployment_succeeded": build_deployment_succeeded,
    "deployment_failed": build_deployment_failed,
    "deployment_rolled_back": build_deployment_rolled_back,
    "workflow_completed": build_workflow_completed,
    "workflow_failed": build_workflow_failed,
    "workflow_waiting_approval": build_workflow_waiting_approval,
    "dangerous_action_confirmation": build_dangerous_action_confirmation,
    "scheduled_workflow_executed": build_scheduled_workflow_executed,
    "scheduled_workflow_failed": build_scheduled_workflow_failed,
    "suspicious_login": build_suspicious_login,
    "new_login_detected": build_new_login_detected,
    "login_from_new_device": build_login_from_new_device,
    "login_from_new_country": build_login_from_new_country,
    "mfa_enabled": build_mfa_enabled,
    "mfa_disabled": build_mfa_disabled,
    "recovery_codes_regenerated": build_recovery_codes_regenerated,
    "oauth_permission_changed": build_oauth_permission_changed,
    "security_alert": build_security_alert,
    "abuse_detected": build_abuse_detected,
    "new_feature": build_new_feature,
    "zyntry_beta_invitation": build_zyntry_beta_invitation,
    "fix_notification": build_fix_notification,
    "maintenance_notice": build_maintenance_notice,
    "incident_notification": build_incident_notification,
    "service_restored": build_service_restored,
    "status_update": build_status_update,
    "new_user_registered": build_new_user_registered,
    "new_organization_created": build_new_organization_created,
    "large_payment_received": build_large_payment_received,
    "runtime_repeatedly_failing": build_runtime_repeatedly_failing,
    "high_infrastructure_usage_alert": build_high_infrastructure_usage_alert,
    "support_received": build_support_received,
    "support_ticket_created": build_support_ticket_created,
    "support_updated": build_support_updated,
    "support_resolved": build_support_resolved,
}


async def send_email(
    template_name: str,
    to: str | list[str],
    *,
    reply_to: str | None = None,
    from_email: str | None = None,
    from_name: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if template_name not in EMAIL_TEMPLATES:
        raise ValueError(f"Unknown email template: {template_name}")
    html, text = EMAIL_TEMPLATES[template_name](**kwargs)
    subject = template_name.replace("_", " ").title().replace("Email", "email").replace("Mfa", "MFA")

    resolved_from = from_email or "noreply@zyntry.space"
    if from_name and "<" not in resolved_from:
        resolved_from = f"{from_name} <{resolved_from}>"

    if not settings.SENDBYTE_KEY:
        logger.warning("SENDBYTE_KEY is not configured; skipping email for template %s to %s", template_name, to)
        return {"success": False, "template": template_name, "to": to, "error": "email_not_configured"}
    client = get_sendbyte_client()
    try:
        result = await client.send(
            to=to,
            subject=subject,
            html=html,
            text=text,
            from_email=resolved_from,
            reply_to=reply_to,
        )
        return {"success": True, "template": template_name, "to": to, "data": result}
    except SendByteError as e:
        logger.error("SendByte email failed for template %s", template_name, extra={"to": to, "error": str(e)})
        return {"success": False, "template": template_name, "to": to, "error": str(e)}


async def send_email_task(template_name: str, to: str | list[str], **kwargs: Any) -> dict[str, Any]:
    return await send_email(template_name, to, **kwargs)
