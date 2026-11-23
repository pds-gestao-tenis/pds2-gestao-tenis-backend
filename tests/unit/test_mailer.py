import json
from unittest.mock import patch

from pydantic import SecretStr

from app.core.config import Settings
from app.core.mailer import Email, LogMailer, ResendMailer, build_mailer, send_all


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"id": "abc"}'


def test_resend_mailer_posts_the_email():
    mailer = ResendMailer("re_chave", "Clube <nao-responda@spyno.app>")
    with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
        mailer.send(Email(to="ana@example.com", subject="Assunto", text="Corpo"))
    request = urlopen.call_args.args[0]
    assert request.full_url == "https://api.resend.com/emails"
    assert request.get_header("Authorization") == "Bearer re_chave"
    assert json.loads(request.data) == {
        "from": "Clube <nao-responda@spyno.app>",
        "to": ["ana@example.com"],
        "subject": "Assunto",
        "text": "Corpo",
    }


def test_build_mailer_uses_resend_only_with_a_key():
    assert isinstance(build_mailer(Settings(_env_file=None)), LogMailer)
    keyed = build_mailer(Settings(_env_file=None, resend_api_key=SecretStr("re_x")))
    assert isinstance(keyed, ResendMailer)


def test_send_all_keeps_going_after_a_failure():
    sent = []

    class Flaky:
        def send(self, email):
            if email.to == "falha@example.com":
                raise OSError("timeout")
            sent.append(email.to)

    send_all(
        Flaky(),
        [Email("falha@example.com", "a", "b"), Email("ok@example.com", "a", "b")],
    )
    assert sent == ["ok@example.com"]
