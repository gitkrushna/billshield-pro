import smtplib
import ssl
from email.message import EmailMessage


class SMTPEmail:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        username: str = "",
        password: str = "",
        starttls: bool = True,
    ):
        self.host, self.port, self.sender = host, port, sender
        self.username, self.password, self.starttls = username, password, starttls
        if username and not starttls:
            raise ValueError("SMTP credentials require TLS")

    def send(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self.sender, recipient, subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.ehlo()
            if self.starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)
