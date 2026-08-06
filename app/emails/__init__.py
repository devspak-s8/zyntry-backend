from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.sendbyte import SendByteError, get_sendbyte_client
import logging

logger = logging.getLogger(__name__)

_APP_NAME = "Zyntra"
_APP_URL = settings.APP_URL or "https://app.zyntry.ai"


_BASE_STYLE = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
"""

_BASE_BG = "#f8fafc"
_CARD_BG = "#ffffff"
_ACCENT_BG = "#7c3aed"
_TEXT_PRIMARY = "#334155"
_TEXT_SECONDARY = "#64748b"
_BORDER = "#e2e8f0"
_ACCENT = "#7c3aed"


def _gradient_icon(svg: str) -> str:
    return f'''<div style="width:48px;height:48px;background:{_CARD_BG};border-radius:12px;display:inline-flex;align-items:center;justify-content:center;margin-bottom:16px;">{svg}</div>'''


_WELCOME_SVG = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{accent}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>'


def build_email(name: str, title: str, subtitle: str, body_html: str, cta_text: str | None = None, cta_url: str | None = None, footer_text: str | None = None) -> str:
    accent = _ACCENT
    footer = footer_text or f"If you didn't expect this email, you can safely ignore it."
    svg = _WELCOME_SVG.format(accent=accent)
    icon = _gradient_icon(svg) if name == "welcome" else _gradient_icon(svg)
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
            <td style="background:{_ACCENT_BG};padding:32px 32px 28px;text-align:center;">
              {icon}
              <h1 style="color:#ffffff;margin:0 0 8px;font-size:22px;font-weight:700;letter-spacing:-0.3px;">{title}</h1>
              <p style="color:rgba(255,255,255,0.85);margin:0;font-size:14px;line-height:1.5;">{subtitle}</p>
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
        title="Reset your password",
        subtitle=f"Hi {display},",
        body_html=f"We received a request to reset your password. Click the button below to set a new password. This link expires in 1 hour and can only be used once.",
        cta_text="Reset Password",
        cta_url=f"{_APP_URL}/reset-password?token={token}",
    )
    text = build_email_text(
        title="Reset your password",
        body=f"We received a request to reset your password. Click below to set a new password.\n\nThis link expires in 1 hour.\n\n{_APP_URL}/reset-password?token={token}",
        cta_text="Reset Password",
        cta_url=f"{_APP_URL}/reset-password?token={token}",
    )
    return html, text


def build_runtime_ready(runtime_name: str) -> tuple[str, str]:
    html = build_email(
        title=f"Your runtime is ready",
        subtitle=f"Runtime '{runtime_name}'",
        body_html=f"Your runtime has been successfully built and is now active. You can start sending requests to the runtime API endpoint using your API key.",
        cta_text="View Runtime",
        cta_url=f"{_APP_URL}/runtimes",
    )
    text = build_email_text(
        title=f"Your runtime is ready",
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
        body_html=f"Your runtime has been successfully re-synchronized. All connected sources, tools, and knowledge bases have been updated.",
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
    html, text = (build_email(
        title=f"{provider} connected successfully",
        subtitle=f"Source '{display}'",
        body_html=f"The {provider} source has been successfully connected and will begin syncing your data.",
        cta_text="View Source",
        cta_url=f"{_APP_URL}/sources",
    ), build_email_text(f"{provider} connected successfully", f"Source '{display}' connected. Syncing will begin automatically.", "View Source", f"{_APP_URL}/sources"))
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


def build_password_changed() -> tuple[str, str]:
    html = build_email(
        title="Password changed successfully",
        subtitle="Security",
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
    "email_verified": build_email_verified,
    "password_reset": build_password_reset,
    "password_changed": build_password_changed,
    "runtime_ready": build_runtime_ready,
    "runtime_build_started": build_runtime_build_started,
    "runtime_failed": build_runtime_failed,
    "runtime_sync_finished": build_runtime_sync_finished,
    "runtime_sync_failed": build_runtime_sync_failed,
    "runtime_paused": build_runtime_paused,
    "runtime_resumed": build_runtime_resumed,
    "runtime_deleted": build_runtime_deleted,
    "github_connected": lambda name: build_source_connected("GitHub", name),
    "notion_connected": lambda name: build_source_connected("Notion", name),
    "google_drive_connected": lambda name: build_source_connected("Google Drive", name),
    "source_sync_finished": build_source_sync_finished,
    "source_sync_failed": build_source_sync_failed,
    "source_reauth": build_source_reauth,
    "discord_connected": lambda name: build_tool_connected("Discord"),
    "slack_connected": lambda name: build_tool_connected("Slack"),
    "tool_expired": build_tool_expired,
    "api_key_created": build_api_key_created,
    "api_key_rotated": build_api_key_rotated,
    "api_key_revoked": build_api_key_revoked,
    "api_abuse_detected": build_api_abuse_detected,
    "wallet_success": build_wallet_success,
    "wallet_failed": build_wallet_failed,
    "low_balance": build_low_balance,
    "usage_summary": build_usage_summary,
    "invoice_available": build_invoice_available,
    "suspicious_login": build_suspicious_login,
    "security_alert": build_security_alert,
    "mfa_enabled": build_mfa_enabled,
    "mfa_disabled": build_mfa_disabled,
    "new_feature": build_new_feature,
    "fix_notification": build_fix_notification,
    "maintenance_notice": build_maintenance_notice,
    "status_update": build_status_update,
    "support_received": build_support_received,
    "support_updated": build_support_updated,
    "support_resolved": build_support_resolved,
}


async def send_email(template_name: str, to: str | list[str], **kwargs: Any) -> dict[str, Any]:
    if template_name not in EMAIL_TEMPLATES:
        raise ValueError(f"Unknown email template: {template_name}")
    html, text = EMAIL_TEMPLATES[template_name](**kwargs)
    subject = template_name.replace("_", " ").title().replace("Email", "email").replace("Mfa", "MFA")
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
            from_email="hello@zyntry.ai",
        )
        return {"success": True, "template": template_name, "to": to, "data": result}
    except SendByteError as e:
        logger.error("SendByte email failed for template %s", template_name, extra={"to": to, "error": str(e)})
        return {"success": False, "template": template_name, "to": to, "error": str(e)}


async def send_email_task(template_name: str, to: str | list[str], **kwargs: Any) -> dict[str, Any]:
    return await send_email(template_name, to, **kwargs)
