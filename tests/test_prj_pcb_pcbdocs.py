from pathlib import Path

from server.parsers.prj_pcb import parse_prj_pcb


def test_extracts_pcbdoc_paths(tmp_path: Path):
    prj = tmp_path / "Demo.PrjPcb"
    prj.write_text(
        "[Document1]\nDocumentPath=sheet1.SchDoc\n"
        "[Document2]\nDocumentPath=Board_1_0.PcbDoc\n"
        "[Document3]\nDocumentPath=sub\\sheet2.SchDoc\n",
        encoding="utf-8",
    )
    data = parse_prj_pcb(str(prj))
    assert len(data.sheet_paths) == 2
    assert len(data.pcb_doc_paths) == 1
    assert data.pcb_doc_paths[0].endswith("Board_1_0.PcbDoc")


def test_no_pcbdoc_is_empty_list(tmp_path: Path):
    prj = tmp_path / "Demo.PrjPcb"
    prj.write_text("[Document1]\nDocumentPath=sheet1.SchDoc\n", encoding="utf-8")
    assert parse_prj_pcb(str(prj)).pcb_doc_paths == []
