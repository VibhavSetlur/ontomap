import json
from ontomap import cli


def test_cli_go_text_consumer(capsys):
    assert cli.main(["map", "--method", "go-text", "--text", "DNA repair helicase", "--top-k", "2", "--quiet"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["provenance"]["method"] == "go-text"
    assert len(output["predictions"]) == 2


def test_cli_rejects_go_identifier_mode(capsys):
    assert cli.main(["map", "--method", "go-text", "--sso", "SSO:1"]) == 2
    assert "accepts" in capsys.readouterr().err
