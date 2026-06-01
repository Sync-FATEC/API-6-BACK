"""Envio de e-mails transacionais via SMTP (Gmail)."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from asg_sistema.config import config


def enviar_email_reset_senha(destinatario: str, link_reset: str) -> None:
    """Envia e-mail com link de redefinição de senha via Gmail SMTP."""

    # TODO: Configure ASG_EMAIL_REMETENTE e ASG_EMAIL_SENHA_APP no .env antes de usar.
    if not config.email_remetente or not config.email_senha_app:
        raise RuntimeError(
            "Envio de e-mail não configurado. "
            "Defina ASG_EMAIL_REMETENTE e ASG_EMAIL_SENHA_APP no .env."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Redefinição de senha - ASG GeoQuery"
    msg["From"] = config.email_remetente
    msg["To"] = destinatario

    corpo_texto = (
        "Você solicitou a redefinição de senha do ASG GeoQuery.\n\n"
        "Acesse o link abaixo para criar uma nova senha (válido por 15 minutos):\n\n"
        f"{link_reset}\n\n"
        "Se não foi você, ignore este e-mail."
    )

    corpo_html = f"""
    <html><body style="font-family:sans-serif;color:#1e293b;">
      <p>Você solicitou a redefinição de senha do <strong>ASG GeoQuery</strong>.</p>
      <p>Clique no botão abaixo para criar uma nova senha
         (válido por <strong>15 minutos</strong>):</p>
      <p style="margin:24px 0;">
        <a href="{link_reset}"
           style="background:#16a34a;color:#fff;padding:12px 24px;
                  border-radius:8px;text-decoration:none;font-weight:600;">
          Redefinir senha
        </a>
      </p>
      <p style="color:#64748b;font-size:13px;">
        Se não foi você quem solicitou, ignore este e-mail.
      </p>
    </body></html>
    """

    msg.attach(MIMEText(corpo_texto, "plain"))
    msg.attach(MIMEText(corpo_html, "html"))

    # TODO: Se usar outro provedor (Outlook, SendGrid etc.), ajuste host/porta abaixo.
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
        servidor.login(config.email_remetente, config.email_senha_app)
        servidor.sendmail(config.email_remetente, destinatario, msg.as_string())
