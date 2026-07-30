from docuforge.__main__ import main


def test_main_prints_development_message(capsys) -> None:
    main()

    captured = capsys.readouterr()

    assert captured.out == "DocuForge development build\n"