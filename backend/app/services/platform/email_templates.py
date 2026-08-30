"""IFNOTUS transactional email layouts — brand-aligned, inbox-friendly.

Design notes:
- Multipart callers always get plain text + HTML.
- Preheaders improve Gmail/Outlook inbox snippets.
- Tone variants (ok / warn / info / code) keep hierarchy without spammy styling.
- Avoid ALL-CAPS subjects, shortener links, and image-only bodies (callers use text).
"""

from __future__ import annotations

from html import escape
from typing import Literal

ACCOUNT_URL = "https://ifnotus.space/account"
BILLING_URL = "https://ifnotus.space/account?panel=billing"
PLANS_URL = "https://ifnotus.space/account/plans"
SUPPORT_URL = "https://ifnotus.space/account"
SITE_URL = "https://ifnotus.space"
SUPPORT_EMAIL = "support@ifnotus.space"

Tone = Literal["ok", "warn", "info", "code", "neutral"]

_TONE_BAR = {
    "ok": "#059669",
    "warn": "#d97706",
    "info": "#ff6c2c",
    "code": "#2563eb",
    "neutral": "#ff6c2c",
}


def _esc(value: str | None) -> str:
    return escape(value or "", quote=True)


def _btn(href: str, label: str) -> str:
    return (
        f'<a href="{_esc(href)}" style="display:inline-block;background:#ff6c2c;color:#ffffff;'
        f'text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:700;'
        f'font-size:14px;letter-spacing:-0.01em;">{_esc(label)}</a>'
    )


def _meta_row(label: str, value: str) -> str:
    return (
        f'<tr>'
        f'<td style="padding:8px 0;font-size:12px;letter-spacing:.06em;text-transform:uppercase;'
        f'color:#6b7280;width:38%;">{_esc(label)}</td>'
        f'<td style="padding:8px 0;font-size:15px;font-weight:600;color:#161a1d;text-align:right;">'
        f'{_esc(value)}</td>'
        f"</tr>"
    )


def wrap(
    title: str,
    inner: str,
    *,
    preheader: str = "",
    tone: Tone = "info",
    cta_href: str | None = None,
    cta_label: str | None = None,
) -> str:
    """Full HTML document with IFNOTUS mark, accent rail, and quiet footer."""
    bar = _TONE_BAR.get(tone, _TONE_BAR["info"])
    pre = _esc(preheader or title)
    cta = ""
    if cta_href and cta_label:
        cta = f'<p style="margin:22px 0 0;">{_btn(cta_href, cta_label)}</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>{_esc(title)}</title>
</head>
<body style="margin:0;padding:0;background:#ebe6df;font-family:'Figtree',Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#161a1d;-webkit-font-smoothing:antialiased;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#ebe6df;opacity:0;">
    {pre}
    {"&nbsp;&zwnj;" * 12}
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ebe6df;padding:28px 12px;">
    <tr><td align="center">
      <table role="presentation" width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #ddd6cc;box-shadow:0 12px 40px rgba(22,26,29,0.08);">
        <tr>
          <td style="background:#161a1d;padding:0;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="width:6px;background:{bar};"></td>
                <td style="padding:22px 26px 18px;">
                  <table role="presentation" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="width:36px;height:36px;background:#ff6c2c;border-radius:9px;text-align:center;vertical-align:middle;font-family:'Sora',Segoe UI,sans-serif;font-size:13px;font-weight:800;color:#ffffff;letter-spacing:-0.04em;">IF</td>
                      <td style="padding-left:12px;vertical-align:middle;">
                        <p style="margin:0;font-family:'Sora',Segoe UI,sans-serif;font-size:15px;font-weight:700;letter-spacing:-0.03em;color:#ffffff;">IFNOTUS</p>
                        <p style="margin:2px 0 0;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#ff6c2c;">Hosting that stays yours</p>
                      </td>
                    </tr>
                  </table>
                  <h1 style="margin:18px 0 0;font-family:'Sora',Segoe UI,sans-serif;font-size:22px;line-height:1.25;font-weight:700;letter-spacing:-0.03em;color:#ffffff;">{_esc(title)}</h1>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:26px 28px 8px;font-size:15px;line-height:1.6;color:#161a1d;">
            {inner}
            {cta}
          </td>
        </tr>
        <tr>
          <td style="padding:18px 28px 26px;border-top:1px solid #eee8e0;">
            <p style="margin:0;font-size:12px;line-height:1.55;color:#6b7280;">
              IFNOTUS · <a href="{SITE_URL}" style="color:#ff6c2c;text-decoration:none;">ifnotus.space</a>
              · <a href="mailto:{SUPPORT_EMAIL}" style="color:#ff6c2c;text-decoration:none;">{SUPPORT_EMAIL}</a>
            </p>
            <p style="margin:8px 0 0;font-size:11px;line-height:1.5;color:#9ca3af;">
              This is a transactional message about your IFNOTUS account. You received it because of an action on your account or an alert you configured.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def wrap_plain(title: str, body: str, *, footer_url: str = ACCOUNT_URL) -> str:
    return (
        f"{title}\n"
        f"{'─' * min(40, max(12, len(title)))}\n\n"
        f"{body.strip()}\n\n"
        f"— IFNOTUS\n{footer_url}\n{SUPPORT_EMAIL}\n"
    )


def simple_notice(
    *,
    name: str,
    title: str,
    paragraphs: list[str],
    tone: Tone = "info",
    cta_href: str | None = None,
    cta_label: str | None = None,
    preheader: str = "",
) -> tuple[str, str, str]:
    """Generic branded notice used when callers only have text."""
    hi = f"Hi {name}," if name and name.lower() not in {"there", "customer"} else "Hello,"
    text_bits = [hi, ""] + paragraphs + [""]
    if cta_href:
        text_bits.append(cta_href)
    text = wrap_plain(title, "\n".join(text_bits), footer_url=cta_href or ACCOUNT_URL)
    html_inner = f"<p style=\"margin:0 0 14px;\">{_esc(hi)}</p>" + "".join(
        f'<p style="margin:0 0 14px;">{_esc(p)}</p>' for p in paragraphs
    )
    html = wrap(
        title,
        html_inner,
        preheader=preheader or (paragraphs[0] if paragraphs else title),
        tone=tone,
        cta_href=cta_href,
        cta_label=cta_label,
    )
    return title, text, html


def security_code(
    *,
    title: str,
    code: str,
    minutes: int,
    context: str,
    recipient_hint: str = "",
    validity_label: str | None = None,
) -> tuple[str, str, str]:
    """OTP / device-approval style email — large monospace code, short TTL."""
    hint = f" {recipient_hint}" if recipient_hint else ""
    validity = validity_label or f"{minutes} minutes"
    text = wrap_plain(
        title,
        f"{context}{hint}\n\nYour code: {code}\nValid for {validity}.\n\n"
        f"If you did not request this, you can ignore this message.",
        footer_url=SITE_URL,
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">{_esc(context)}{_esc(hint)}</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:8px 0 16px;background:#f7f4ef;border-radius:14px;border:1px dashed #d4cdc2;">
          <tr><td align="center" style="padding:22px 16px;">
            <p style="margin:0 0 6px;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:#6b7280;">One-time code</p>
            <p style="margin:0;font-family:'JetBrains Mono',Consolas,Monaco,monospace;font-size:32px;letter-spacing:.28em;font-weight:700;color:#161a1d;">{_esc(code)}</p>
            <p style="margin:10px 0 0;font-size:13px;color:#6b7280;">Valid for {_esc(validity)}</p>
          </td></tr>
        </table>
        <p style="margin:0;font-size:13px;color:#6b7280;">If you did not request this, you can ignore this message. Never share the code.</p>
        """,
        preheader=f"Your IFNOTUS code is {code}. Valid for {validity}.",
        tone="code",
    )
    return title, text, html


def password_reset(*, name: str, link: str, minutes: int) -> tuple[str, str, str]:
    title = "Reset your IFNOTUS password"
    text = wrap_plain(
        title,
        f"Hi {name},\n\nWe received a request to reset your password.\n"
        f"Open this link within {minutes} minutes:\n{link}\n\n"
        f"If you did not request this, you can ignore this email.",
        footer_url=SITE_URL,
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">We received a request to reset your IFNOTUS password. Use the button below within <strong>{minutes} minutes</strong>.</p>
        <p style="margin:0;font-size:13px;color:#6b7280;">If you did not request this, ignore this email — your password stays the same.</p>
        """,
        preheader=f"Password reset link — expires in {minutes} minutes.",
        tone="code",
        cta_href=link,
        cta_label="Choose a new password",
    )
    return title, text, html


def invoice_placed(
    *,
    name: str,
    invoice: str,
    amount: str,
    currency: str,
    plan: str,
    momo_network: str,
    momo_number: str,
    momo_name: str,
    invoice_url: str = ACCOUNT_URL,
) -> tuple[str, str, str]:
    title = "Your IFNOTUS invoice is ready"
    text = wrap_plain(
        title,
        f"Hi {name},\n\n"
        f"Invoice {invoice} for {currency} {amount} ({plan}) is ready.\n"
        f"Pay {momo_network} Mobile Money to merchant {momo_number} "
        f"(account name {momo_name}). Use {invoice} as the reference.\n"
        f"Then open the invoice and enter the Mobile Money transaction ID.\n\n"
        f"{invoice_url}",
        footer_url=invoice_url,
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">Pay Mobile Money to the IFNOTUS merchant number, then share the transaction ID so we can activate hosting.</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f4ef;border-radius:14px;padding:4px 16px;margin:4px 0 16px;">
          {_meta_row("Invoice", invoice)}
          {_meta_row("Package", plan)}
          {_meta_row("Amount", f"{currency} {amount}")}
        </table>
        <p style="margin:0 0 6px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#6b7280;font-weight:700;">Merchant Mobile Money</p>
        <p style="margin:0;">{_esc(momo_network)} · {_esc(momo_number)}<br>
        Account name: {_esc(momo_name)}<br>
        Reference: <strong>{_esc(invoice)}</strong></p>
        """,
        preheader=f"Invoice {invoice} · {currency} {amount} · pay via Mobile Money",
        tone="info",
        cta_href=invoice_url,
        cta_label="Open invoice",
    )
    return title, text, html


def payment_received(*, name: str, invoice: str) -> tuple[str, str, str]:
    title = "Payment Details Received"
    text = wrap_plain(
        title,
        f"Hi {name},\n\nWe have received your payment reference for invoice {invoice}. "
        f"Our billing desk is verifying the transaction. Your hosting environment will be activated immediately once confirmed.",
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">We have received your payment reference for invoice <strong>{_esc(invoice)}</strong>.</p>
        <p style="margin:0;">Our billing desk is verifying the transaction. Your hosting environment will be activated and provisioned immediately once confirmed.</p>
        """,
        preheader=f"Payment details received for invoice {invoice}. Verification in progress.",
        tone="info",
        cta_href=ACCOUNT_URL,
        cta_label="View account status",
    )
    return title, text, html


def payment_confirmed(*, name: str, invoice: str, detail: str | None = None) -> tuple[str, str, str]:
    title = "Payment Verified & Accepted"
    detail_line = detail or "Your payment is verified and accepted. Hosting infrastructure and server provisioning are in progress."
    text = wrap_plain(
        title,
        f"Hi {name},\n\nPayment for invoice {invoice} is verified and accepted.\n{detail_line}",
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">Payment for invoice <strong>{_esc(invoice)}</strong> has been verified and accepted by billing.</p>
        <p style="margin:0;">{_esc(detail_line)}</p>
        """,
        preheader=f"Payment verified for invoice {invoice}.",
        tone="ok",
        cta_href=ACCOUNT_URL,
        cta_label="Open control panel",
    )
    return title, text, html


def payment_rejected(*, name: str, invoice: str, notes: str | None = None) -> tuple[str, str, str, str]:
    title = "Payment Verification Unsuccessful"
    reason = f" Details: {notes}" if notes else ""
    text = wrap_plain(
        title,
        f"Hi {name},\n\nWe could not verify the payment transaction for invoice {invoice}.{reason}\n"
        f"Please verify your reference number or transaction ID, or contact billing support.\n{ACCOUNT_URL}",
    )
    note_html = f" <p style='margin:10px 0 0; color:#b42318;'><strong>Note:</strong> {_esc(notes)}</p>" if notes else ""
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 10px;">We were unable to verify the transaction details for invoice <strong>{_esc(invoice)}</strong>.</p>
        {note_html}
        <p style="margin:14px 0 0;">Please check your Mobile Money reference code and resubmit, or reach out to our billing desk for assistance.</p>
        """,
        preheader=f"Payment verification required for invoice {invoice}.",
        tone="warn",
        cta_href=ACCOUNT_URL,
        cta_label="Review invoice & retry",
    )
    sms = (
        f"Payment verification for invoice {invoice} was unsuccessful. "
        f"Please check your transaction reference at ifnotus.space/account or contact support."
    )
    return title, text, html, sms


def hosting_ready(*, name: str, hostname: str) -> tuple[str, str, str]:
    title = "Hosting Environment Active & Live"
    url = f"https://{hostname}" if hostname else ACCOUNT_URL
    text = wrap_plain(
        title,
        f"Hi {name},\n\nYour hosting environment is fully provisioned and live. You can now manage files, databases, mail, and SSL.\n"
        f"Website: {url}\nControl Panel: {ACCOUNT_URL}",
        footer_url=url,
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">Your hosting environment is fully provisioned, DNS is configured, and your site is live.</p>
        <p style="margin:0 0 14px;font-size:14px;"><strong>Site URL:</strong> <a href="{_esc(url)}" style="color:#2563eb;">{_esc(url)}</a></p>
        <p style="margin:0;color:#64748b;font-size:13px;">Manage your web files, databases, mailboxes, and domains directly from your control panel.</p>
        """,
        preheader=f"Hosting environment is live at {hostname or 'your domain'}.",
        tone="ok",
        cta_href=ACCOUNT_URL,
        cta_label="Open hosting control panel",
    )
    return title, text, html


def hosting_ready_sms(*, hostname: str) -> str:
    if hostname:
        return (
            f"Your hosting on {hostname} is active and live! "
            f"Access control panel: ifnotus.space/account"
        )
    return "Your hosting is active and live! Access control panel: ifnotus.space/account"


def hosting_failed(*, name: str, invoice: str | None = None) -> tuple[str, str, str, str]:
    inv = invoice or "your order"
    title = "Hosting setup needs attention"
    text = wrap_plain(
        title,
        f"Hi {name},\n\nHosting setup for {inv} did not finish. "
        f"Our team will follow up. You can also open support in your account.\n{ACCOUNT_URL}",
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0;">Hosting setup for <strong>{_esc(inv)}</strong> did not finish.
        Our team will follow up — you can also open support in your account.</p>
        """,
        preheader=f"Setup for {inv} needs a follow-up from our team.",
        tone="warn",
        cta_href=ACCOUNT_URL,
        cta_label="Open your account",
    )
    sms = (
        f"Hosting setup for {inv} did not complete. "
        f"Support will follow up. ifnotus.space/account"
    )
    return title, text, html, sms


def hosting_terminated(*, name: str) -> tuple[str, str, str, str]:
    title = "Hosting ended"
    text = wrap_plain(
        title,
        f"Hi {name},\n\nThe subscription was not renewed. Resources have been released. "
        f"Open Plans if you want to start again.\n{PLANS_URL}",
        footer_url=PLANS_URL,
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0;">The subscription was not renewed and resources have been released.
        You can start again anytime from Plans.</p>
        """,
        preheader="Hosting ended after non-renewal. You can start again from Plans.",
        tone="warn",
        cta_href=PLANS_URL,
        cta_label="See plans",
    )
    sms = "Hosting ended after non-renewal. Start again: ifnotus.space/account/plans"
    return title, text, html, sms


def renewal_reminder(
    *,
    name: str,
    days_left: int,
    expires_on: str,
    plan: str,
    auto_renew: bool,
) -> tuple[str, str, str, str]:
    when = "today" if days_left <= 1 else f"in {days_left} days"
    title = f"Hosting renews {when}"
    if auto_renew:
        action = (
            "Auto-renew is on. Keep Mobile Money ready — we'll send an invoice or extend "
            "your hosting when the period ends. You can manage this in Billing."
        )
        sms = (
            f"Hosting ({plan}) renews {when} ({expires_on}). Auto-renew ON. "
            f"Billing: ifnotus.space/account"
        )
    else:
        action = (
            f"Auto-renew is off. Renew from Billing before {expires_on} or your site may pause "
            f"after a short grace period."
        )
        sms = (
            f"Hosting ({plan}) expires {when} ({expires_on}). Auto-renew OFF — renew now: "
            f"ifnotus.space/account"
        )
    text = wrap_plain(
        title,
        f"Hi {name},\n\nYour IFNOTUS {plan} hosting expires {when} on {expires_on}.\n"
        f"{action}\n\n{BILLING_URL}",
        footer_url=BILLING_URL,
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">Your <strong>{_esc(plan)}</strong> hosting expires
        <strong>{_esc(when)}</strong> ({_esc(expires_on)}).</p>
        <p style="margin:0;">{_esc(action)}</p>
        """,
        preheader=f"{plan} renews {when} · {expires_on}",
        tone="info" if auto_renew else "warn",
        cta_href=BILLING_URL,
        cta_label="Open billing",
    )
    return title, text, html, sms


def auto_renewed(
    *,
    name: str,
    plan: str,
    expires_on: str,
) -> tuple[str, str, str, str]:
    title = "Hosting auto-renewed"
    text = wrap_plain(
        title,
        f"Hi {name},\n\nYour IFNOTUS {plan} hosting was renewed automatically. "
        f"It is now active until {expires_on}.\n\n{BILLING_URL}",
        footer_url=BILLING_URL,
    )
    sms = f"Hosting ({plan}) auto-renewed until {expires_on}. Account: ifnotus.space/account"
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0;">Your <strong>{_esc(plan)}</strong> hosting was renewed automatically
        and stays online until <strong>{_esc(expires_on)}</strong>.</p>
        """,
        preheader=f"{plan} auto-renewed until {expires_on}.",
        tone="ok",
        cta_href=BILLING_URL,
        cta_label="View billing",
    )
    return title, text, html, sms


def subscription_renewed(
    *,
    name: str,
    plan: str,
    expires_on: str,
) -> tuple[str, str, str, str]:
    title = "Subscription renewed"
    text = wrap_plain(
        title,
        f"Hi {name},\n\nYour IFNOTUS {plan} hosting is extended until {expires_on}.\n\n{BILLING_URL}",
        footer_url=BILLING_URL,
    )
    sms = f"Hosting ({plan}) renewed until {expires_on}. ifnotus.space/account"
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0;">Your <strong>{_esc(plan)}</strong> hosting is extended until
        <strong>{_esc(expires_on)}</strong>.</p>
        """,
        preheader=f"{plan} renewed until {expires_on}.",
        tone="ok",
        cta_href=BILLING_URL,
        cta_label="View billing",
    )
    return title, text, html, sms


def renewal_payment_needed(
    *,
    name: str,
    plan: str,
    expires_on: str,
    grace_days: int,
) -> tuple[str, str, str, str]:
    title = "Renewal payment needed"
    text = wrap_plain(
        title,
        f"Hi {name},\n\n"
        f"Your {plan} hosting expired on {expires_on} and auto-renew is on, but we could not "
        f"complete payment automatically. You have about {grace_days} days of grace — "
        f"open Billing, pay the invoice, and keep your site live.\n\n{BILLING_URL}",
        footer_url=BILLING_URL,
    )
    sms = (
        f"Auto-renew — payment needed for {plan} (expired {expires_on}). "
        f"Grace ~{grace_days}d. Pay: ifnotus.space/account"
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">Auto-renew is on for <strong>{_esc(plan)}</strong>, but payment
        still needs your Mobile Money step.</p>
        <p style="margin:0;">Expired on {_esc(expires_on)}. Grace period: about
        <strong>{grace_days} days</strong>.</p>
        """,
        preheader=f"Payment needed for {plan} · ~{grace_days} days grace",
        tone="warn",
        cta_href=BILLING_URL,
        cta_label="Pay and renew",
    )
    return title, text, html, sms


def grace_started(
    *,
    name: str,
    plan: str,
    grace_days: int,
) -> tuple[str, str, str, str]:
    title = "Payment overdue — grace period"
    text = wrap_plain(
        title,
        f"Hi {name},\n\n"
        f"Your {plan} hosting expired. You have {grace_days} days to renew before the site is suspended.\n\n"
        f"{BILLING_URL}",
        footer_url=BILLING_URL,
    )
    sms = f"{plan} expired — {grace_days}d grace left. Renew: ifnotus.space/account"
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0;">Your <strong>{_esc(plan)}</strong> hosting expired.
        You have <strong>{grace_days} days</strong> to renew before suspension.</p>
        """,
        preheader=f"{plan}: {grace_days} days left to renew.",
        tone="warn",
        cta_href=BILLING_URL,
        cta_label="Renew now",
    )
    return title, text, html, sms


def hosting_suspended(*, name: str, reason: str) -> tuple[str, str, str, str]:
    title = "Hosting suspended"
    text = wrap_plain(
        title,
        f"Hi {name},\n\n{reason}\n\nRenew from Billing to restore access.\n{BILLING_URL}",
        footer_url=BILLING_URL,
    )
    sms = "Hosting suspended. Renew to restore: ifnotus.space/account"
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0;">{_esc(reason)}</p>
        """,
        preheader="Hosting suspended — renew to restore access.",
        tone="warn",
        cta_href=BILLING_URL,
        cta_label="Renew and restore",
    )
    return title, text, html, sms


def auto_renew_changed(*, name: str, enabled: bool, plan: str) -> tuple[str, str, str, str]:
    state = "on" if enabled else "off"
    title = f"Auto-renew turned {state}"
    if enabled:
        body = (
            f"Auto-renew is now on for your {plan} hosting. We'll remind you before expiry "
            f"and attempt to keep the site online at the end of the period."
        )
        sms = f"Auto-renew ON for {plan}. Reminders by SMS and email before expiry."
    else:
        body = (
            f"Auto-renew is now off for your {plan} hosting. Renew manually from Billing "
            f"before the expiry date or the site may pause."
        )
        sms = f"Auto-renew OFF for {plan}. Renew manually before expiry: ifnotus.space/account"
    text = wrap_plain(title, f"Hi {name},\n\n{body}\n\n{BILLING_URL}", footer_url=BILLING_URL)
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0;">{_esc(body)}</p>
        """,
        preheader=f"Auto-renew is {state} for {plan}.",
        tone="ok" if enabled else "info",
        cta_href=BILLING_URL,
        cta_label="Billing settings",
    )
    return title, text, html, sms


def upgrade_nudge(
    *,
    name: str,
    plan: str,
    next_plan: str | None = None,
) -> tuple[str, str, str, str]:
    title = "Ready for more room?"
    hint = (
        f"Many customers on {plan} move to {next_plan} when they need more storage, mailboxes, or AI credits."
        if next_plan
        else f"When {plan} feels tight, a higher IFNOTUS package unlocks more storage, mailboxes, and AI help."
    )
    text = wrap_plain(
        title,
        f"Hi {name},\n\n{hint}\n"
        f"Compare packages anytime — upgrade only when you need it.\n\n{PLANS_URL}",
        footer_url=PLANS_URL,
    )
    sms = (
        f"Tip: {plan} still fits? Compare upgrades at ifnotus.space/account/plans"
        if not next_plan
        else f"Tip: consider {next_plan} when you outgrow {plan}. ifnotus.space/account/plans"
    )
    html = wrap(
        title,
        f"""
        <p style="margin:0 0 14px;">Hi {_esc(name)},</p>
        <p style="margin:0 0 14px;">{_esc(hint)}</p>
        <p style="margin:0;">Compare packages anytime — upgrade only when you need it.</p>
        """,
        preheader="Compare IFNOTUS packages when you need more room.",
        tone="neutral",
        cta_href=PLANS_URL,
        cta_label="See packages",
    )
    return title, text, html, sms


def operator_alert(*, subject: str, body: str) -> tuple[str, str, str]:
    title = subject if subject.startswith("IFNOTUS") else f"IFNOTUS · {subject}"
    text = wrap_plain(title, body, footer_url=SITE_URL)
    html = wrap(
        title,
        f'<p style="margin:0;white-space:pre-wrap;font-family:\'JetBrains Mono\',Consolas,monospace;font-size:13px;line-height:1.55;">{_esc(body)}</p>',
        preheader=body[:120],
        tone="warn",
    )
    return title, text, html


# Back-compat alias used by older call sites
_wrap = wrap
