from backend.domains.rtl.adapter import extract_sv
from backend.domains.rtl.yosys import discover_top, _extract_statistics


def test_extract_sv_from_fenced_block():
    raw = "Here you go:\n```systemverilog\nmodule foo(input a);\nendmodule\n```\n"
    sv = extract_sv(raw)
    assert sv.startswith("module foo")
    assert "```" not in sv


def test_extract_sv_falls_back_to_module_keyword():
    raw = "some preamble text module bar(input a); endmodule"
    sv = extract_sv(raw)
    assert sv.startswith("module bar")


def test_discover_top():
    assert discover_top("module counter(input clk); endmodule") == "counter"
    assert discover_top("no top-level keyword present") is None


def test_extract_statistics_parses_yosys_stat_output():
    text = "Number of wires:                 5\nNumber of cells:                 3\n   $_DFF_P_               2\n"
    stats = _extract_statistics(text)
    assert stats["wires"] == 5
    assert stats["cells"] == 3
    assert stats["cell_types"]["$_DFF_P_"] == 2
