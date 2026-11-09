from omnimodel.emails import find_emails


def test_own_domain_and_general_mailbox_come_first():
    text = "Write to jane@gmail.com or info@acme.com.gh or sales@acme.com.gh, hosted by wix: abc@sentry.io logo@2x.png"
    assert find_emails(text, "https://www.acme.com.gh/about") == ["info@acme.com.gh", "sales@acme.com.gh", "jane@gmail.com"]


def test_junk_is_ignored():
    assert find_emails("noreply@acme.com name@example.com photo@x.com.png", "https://acme.com") == []


def test_none_found():
    assert find_emails("", "https://acme.com") == []