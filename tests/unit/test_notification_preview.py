"""Notification presentation never transports transcripts or credential lines."""

from cognis.api.notification_preview import notification_preview


def test_plain_bounded_reply_preview() -> None:
    assert notification_preview("**Ready** [result](https://host.invalid)\nNext step.") == (
        "Ready result Next step."
    )
    assert len(notification_preview("word " * 5000)) <= 240


def test_secret_and_code_lines_are_omitted() -> None:
    assert (
        notification_preview(
            "Completed.\nPassword: fixture-sensitive\n"
            "```python\ncredential_value = 'fixture-sensitive'\n```\n"
            "Authorization: Bearer fixture-sensitive\n"
            "api_key = fixture-sensitive\n"
            "abcdefghijklmnopqrstuvwxyz0123456789\n"
            "Review the result."
        )
        == ""
    )


def test_multiline_credentials_fail_closed_for_the_entire_preview() -> None:
    for content in (
        "Password:\nshort-fixture\nCompleted.",
        "Recovery codes:\n123-456\n789-012",
        "Ready.\n```\nPassword:\n```\nshort-fixture",
    ):
        assert notification_preview(content) == ""
