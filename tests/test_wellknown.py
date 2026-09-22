"""Well-known files are a trust / AI inventory, not traffic."""
from app.omni.site import (PublicFile, inventory_from_files, parse_humans_txt,
                           parse_security_txt)


def test_security_txt_contacts_are_not_a_badge():
    contacts, fields = parse_security_txt(
        "Contact: mailto:sec@acme.example\n"
        "Expires: 2027-01-01T00:00:00.000Z\n"
        "Policy: https://acme.example/security\n"
        "# comment\n"
    )
    assert contacts == ["mailto:sec@acme.example"]
    assert fields["expires"].startswith("2027-01-01")
    assert fields["policy"].endswith("/security")


def test_humans_txt_is_credits_not_headcount():
    lines = parse_humans_txt("# TEAM\nAda Lovelace\nAlan Turing\n\n")
    assert lines == ["Ada Lovelace", "Alan Turing"]


def test_inventory_labels_roles_honestly():
    files = [
        PublicFile(path="/.well-known/security.txt", present=True, status=200,
                   role="trust", contacts=["mailto:sec@acme.example"]),
        PublicFile(path="/llms.txt", present=True, status=200, role="ai"),
        PublicFile(path="/humans.txt", present=False, status=404, role="people"),
    ]
    rows = {row["path"]: row for row in inventory_from_files(files)}
    assert rows["/llms.txt"]["note"].lower().startswith("crawl invitation")
    assert "soc 2" in rows["/.well-known/security.txt"]["note"].lower()
    assert rows["/humans.txt"]["present"] == "no"
