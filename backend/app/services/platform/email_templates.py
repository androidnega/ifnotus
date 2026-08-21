"""Clean HTML email layouts for customer billing and go-live."""

from __future__ import annotations


def _wrap(title: str, inner: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;background:#f4f1ec;font-family:Figtree,Segoe UI,sans-serif;color:#161a1d;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f1ec;padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e7e2db;">
        <tr><td style="background:#161a1d;padding:18px 24px;">
          <p style="margin:0;font-size:13px;letter-spacing:.12em;color:#ff6c2c;font-weight:700;">IFNOTUS</p>
          <h1 style="margin:6px 0 0;font-size:20px;color:#ffffff;">{title}</h1>
        </td></tr>
        <tr><td style="padding:24px;font-size:15px;line-height:1.55;">{inner}</td></tr>
        <tr><td style="padding:0 24px 22px;font-size:12px;color:#6b7280;">
          IFNOTUS · <a href="https://ifnotus.space/account" style="color:#ff6c2c;">Open your account</a>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


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
    invoice_url: str = "https://ifnotus.space/account",
) -> tuple[str, str, str]:
    title = "Your IFNOTUS invoice"
    text = (
        f"Hi {name},\n\n"
        f"Invoice {invoice} for {currency} {amount} ({plan}) is ready.\n"
        f"Pay {momo_network} Mobile Money to the IFNOTUS merchant number {momo_number} "
        f"(account name {momo_name}). Use {invoice} as the reference.\n"
        f"Then open the invoice and enter the Mobile Money transaction ID.\n"
        f"We'll confirm payment and activate your hosting.\n\n"
        f"{invoice_url}\n"
    )
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>Your invoice is ready. Pay Mobile Money to the IFNOTUS merchant number, then share the transaction ID so we can activate hosting.</p>
        <table role="presentation" width="100%" style="background:#f4f1ec;border-radius:12px;padding:14px 16px;margin:16px 0;">
          <tr><td style="font-size:13px;color:#6b7280;">Invoice</td><td align="right" style="font-weight:700;">{invoice}</td></tr>
          <tr><td style="font-size:13px;color:#6b7280;">Package</td><td align="right">{plan}</td></tr>
          <tr><td style="font-size:13px;color:#6b7280;">Amount</td><td align="right" style="font-weight:700;">{currency} {amount}</td></tr>
        </table>
        <p style="margin:0 0 8px;"><strong>Merchant Mobile Money</strong></p>
        <p style="margin:0;">{momo_network} merchant · {momo_number}<br>Account name: {momo_name}<br>Reference: {invoice}</p>
        <p style="margin:16px 0 0;"><a href="{invoice_url}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">Open invoice</a></p>
        """,
    )
    return title, text, html


def payment_received(*, name: str, invoice: str) -> tuple[str, str, str]:
    title = "We received your payment details"
    text = (
        f"Hi {name},\n\nWe have your Mobile Money transaction for invoice {invoice}. "
        f"We'll confirm it and activate your hosting. You'll get another message when it's live.\n"
    )
    html = _wrap(
        title,
        f"<p>Hi {name},</p><p>We have your Mobile Money transaction for invoice <strong>{invoice}</strong>. "
        f"We'll confirm it and activate your hosting. You'll hear from us as soon as it's live.</p>",
    )
    return title, text, html


def payment_confirmed(*, name: str, invoice: str) -> tuple[str, str, str]:
    title = "Payment confirmed — activating hosting"
    text = (
        f"Hi {name},\n\nPayment for invoice {invoice} is confirmed. "
        f"We're activating your hosting now. Watch for a message when it's ready in your account.\n"
    )
    html = _wrap(
        title,
        f"<p>Hi {name},</p><p>Payment for invoice <strong>{invoice}</strong> is confirmed. "
        f"We're activating your hosting now. You'll get a message when it's ready in your account.</p>",
    )
    return title, text, html


def hosting_ready(*, name: str, hostname: str) -> tuple[str, str, str]:
    title = "Your hosting is ready"
    url = f"https://{hostname}" if hostname else "https://ifnotus.space/account"
    text = (
        f"Hi {name},\n\nYour IFNOTUS hosting is ready. Sign in to manage files, domains, and support.\n"
        f"Site: {url}\nAccount: https://ifnotus.space/account\n"
    )
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>Your hosting is live. Everything you need is in your IFNOTUS account.</p>
        <p><a href="{url}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">Open your site</a></p>
        <p style="margin-top:16px;"><a href="https://ifnotus.space/account" style="color:#ff6c2c;">Go to your account</a></p>
        """,
    )
    return title, text, html


ACCOUNT_URL = "https://ifnotus.space/account"
BILLING_URL = "https://ifnotus.space/account?panel=billing"
PLANS_URL = "https://ifnotus.space/account/plans"


def renewal_reminder(
    *,
    name: str,
    days_left: int,
    expires_on: str,
    plan: str,
    auto_renew: bool,
) -> tuple[str, str, str, str]:
    """Returns title, text, html, sms_body."""
    when = "today" if days_left <= 1 else f"in {days_left} days"
    title = f"Hosting renews {when}"
    if auto_renew:
        action = (
            f"Auto-renew is on. Keep Mobile Money ready — we'll send an invoice or extend "
            f"your hosting when the period ends. You can manage this in Billing."
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
    text = (
        f"Hi {name},\n\n"
        f"Your IFNOTUS {plan} hosting expires {when} on {expires_on}.\n"
        f"{action}\n\n"
        f"{BILLING_URL}\n"
    )
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>Your <strong>{plan}</strong> hosting expires <strong>{when}</strong> ({expires_on}).</p>
        <p>{action}</p>
        <p style="margin:16px 0 0;"><a href="{BILLING_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">Open billing</a></p>
        """,
    )
    return title, text, html, sms


def auto_renewed(
    *,
    name: str,
    plan: str,
    expires_on: str,
) -> tuple[str, str, str, str]:
    title = "Hosting auto-renewed"
    text = (
        f"Hi {name},\n\n"
        f"Your IFNOTUS {plan} hosting was renewed automatically. "
        f"It is now active until {expires_on}.\n\n"
        f"{BILLING_URL}\n"
    )
    sms = f"Hosting ({plan}) auto-renewed until {expires_on}. Account: ifnotus.space/account"
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>Your <strong>{plan}</strong> hosting was renewed automatically and stays online until <strong>{expires_on}</strong>.</p>
        <p style="margin:16px 0 0;"><a href="{BILLING_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">View billing</a></p>
        """,
    )
    return title, text, html, sms


def subscription_renewed(
    *,
    name: str,
    plan: str,
    expires_on: str,
) -> tuple[str, str, str, str]:
    title = "Subscription renewed"
    text = (
        f"Hi {name},\n\nYour IFNOTUS {plan} hosting is extended until {expires_on}.\n\n"
        f"{BILLING_URL}\n"
    )
    sms = f"Hosting ({plan}) renewed until {expires_on}. ifnotus.space/account"
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>Your <strong>{plan}</strong> hosting is extended until <strong>{expires_on}</strong>.</p>
        <p style="margin:16px 0 0;"><a href="{BILLING_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">View billing</a></p>
        """,
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
    text = (
        f"Hi {name},\n\n"
        f"Your {plan} hosting expired on {expires_on} and auto-renew is on, but we could not "
        f"complete payment automatically. You have about {grace_days} days of grace — "
        f"open Billing, pay the invoice, and keep your site live.\n\n"
        f"{BILLING_URL}\n"
    )
    sms = (
        f"Auto-renew: payment needed for {plan} (expired {expires_on}). "
        f"Grace ~{grace_days}d. Pay: ifnotus.space/account"
    )
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>Auto-renew is on for <strong>{plan}</strong>, but payment still needs your Mobile Money step.</p>
        <p>Expired on {expires_on}. Grace period: about <strong>{grace_days} days</strong>.</p>
        <p style="margin:16px 0 0;"><a href="{BILLING_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">Pay & renew</a></p>
        """,
    )
    return title, text, html, sms


def grace_started(
    *,
    name: str,
    plan: str,
    grace_days: int,
) -> tuple[str, str, str, str]:
    title = "Payment overdue — grace period"
    text = (
        f"Hi {name},\n\n"
        f"Your {plan} hosting expired. You have {grace_days} days to renew before the site is suspended.\n\n"
        f"{BILLING_URL}\n"
    )
    sms = f"{plan} expired — {grace_days}d grace left. Renew: ifnotus.space/account"
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>Your <strong>{plan}</strong> hosting expired. You have <strong>{grace_days} days</strong> to renew before suspension.</p>
        <p style="margin:16px 0 0;"><a href="{BILLING_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">Renew now</a></p>
        """,
    )
    return title, text, html, sms


def hosting_suspended(*, name: str, reason: str) -> tuple[str, str, str, str]:
    title = "Hosting suspended"
    text = f"Hi {name},\n\n{reason}\n\nRenew from Billing to restore access.\n{BILLING_URL}\n"
    sms = f"Hosting suspended. Renew to restore: ifnotus.space/account"
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>{reason}</p>
        <p style="margin:16px 0 0;"><a href="{BILLING_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">Renew & restore</a></p>
        """,
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
        sms = f"Auto-renew ON for {plan}. Reminders by SMS/email before expiry."
    else:
        body = (
            f"Auto-renew is now off for your {plan} hosting. Renew manually from Billing "
            f"before the expiry date or the site may pause."
        )
        sms = f"Auto-renew OFF for {plan}. Renew manually before expiry: ifnotus.space/account"
    text = f"Hi {name},\n\n{body}\n\n{BILLING_URL}\n"
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>{body}</p>
        <p style="margin:16px 0 0;"><a href="{BILLING_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">Billing settings</a></p>
        """,
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
    text = (
        f"Hi {name},\n\n"
        f"{hint}\n"
        f"Compare packages anytime — no pressure, upgrade only when you need it.\n\n"
        f"{PLANS_URL}\n"
    )
    sms = (
        f"IFNOTUS tip: {plan} still fits? Compare upgrades at ifnotus.space/account/plans"
        if not next_plan
        else f"IFNOTUS tip: consider {next_plan} when you outgrow {plan}. ifnotus.space/account/plans"
    )
    html = _wrap(
        title,
        f"""
        <p>Hi {name},</p>
        <p>{hint}</p>
        <p>Compare packages anytime — upgrade only when you need it.</p>
        <p style="margin:16px 0 0;"><a href="{PLANS_URL}" style="display:inline-block;background:#ff6c2c;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;">See packages</a></p>
        """,
    )
    return title, text, html, sms
