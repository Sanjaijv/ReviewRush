from app.context.symbols import detect_language, extract_symbols


def test_detect_language_by_extension() -> None:
    assert detect_language("src/app.py") == "python"
    assert detect_language("src/app.ts") == "typescript"
    assert detect_language("src/app.go") == "go"
    assert detect_language("README.md") == ""


def test_python_symbols_include_top_level_functions_and_methods() -> None:
    content = (
        "def top_level():\n"
        "    return 1\n"
        "\n"
        "class Foo:\n"
        "    def method_a(self):\n"
        "        return 2\n"
    )

    symbols = extract_symbols("app.py", content, max_symbols=50)
    by_name = {s.name: s for s in symbols}

    assert by_name["top_level"].kind == "function"
    assert by_name["Foo"].kind == "class"
    assert by_name["method_a"].kind == "method"
    assert by_name["top_level"].start_line == 1


def test_python_syntax_error_yields_no_symbols_instead_of_raising() -> None:
    assert extract_symbols("broken.py", "def (:\n", max_symbols=50) == []


def test_javascript_function_and_class_detected() -> None:
    content = "export class Widget {\n  render() {}\n}\n\nfunction helper() {\n  return 1;\n}\n"

    symbols = extract_symbols("widget.js", content, max_symbols=50)
    names = {s.name for s in symbols}

    assert "Widget" in names
    assert "helper" in names


def test_go_function_detected() -> None:
    content = "package main\n\nfunc DoThing(x int) int {\n\treturn x\n}\n"

    symbols = extract_symbols("main.go", content, max_symbols=50)

    assert any(s.name == "DoThing" and s.kind == "function" for s in symbols)


def test_max_symbols_caps_result() -> None:
    content = "\n".join(f"def fn_{i}():\n    pass" for i in range(10))

    symbols = extract_symbols("many.py", content, max_symbols=3)

    assert len(symbols) == 3
