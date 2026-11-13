"""Tests for check_limits.py. Each limit is tested at the boundary and one past it."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_limits as cl  # noqa: E402


def cpp_function(name: str, body_lines: int) -> str:
    # header + body_lines + closing brace = body_lines + 2 lines in total
    return f"int {name}() {{\n" + "    x();\n" * body_lines + "}\n"


def kt_function(name: str, body_lines: int) -> str:
    return f"fun {name}() {{\n" + "    x()\n" * body_lines + "}\n"


class FunctionLength(unittest.TestCase):
    def test_cpp_at_limit_passes_and_one_over_fails(self):
        self.assertEqual(cl.brace_functions(cpp_function("f", 58), "cpp"), [(1, 60)])
        self.assertEqual(cl.brace_functions(cpp_function("f", 59), "cpp"), [(1, 61)])

    def test_cpp_methods_inside_namespace_and_struct_are_found(self):
        src = "namespace a {\nstruct S {\n" + cpp_function("m", 3) + "};\n}\n"
        self.assertEqual(cl.brace_functions(src, "cpp"), [(3, 5)])

    def test_template_class_keyword_is_not_a_container(self):
        src = "template <class T>\nT f(T v) {\n  return v;\n}\n"
        self.assertEqual(cl.brace_functions(src, "cpp"), [(1, 4)])

    def test_braces_in_strings_and_comments_are_ignored(self):
        src = 'void f() {\n  s = "}}}";\n  // }\n  /* { */\n}\n'
        self.assertEqual(cl.brace_functions(src, "cpp"), [(1, 5)])

    def test_namespace_scope_data_tables_are_not_functions(self):
        src = "const int t[] = {\n" + "1,\n" * 100 + "};\n"
        self.assertEqual(cl.brace_functions(src, "cpp"), [])

    def test_kotlin_class_members_and_anonymous_objects(self):
        src = ("class A(val x: Int) {\n" + kt_function("f", 2)
               + "  private val cb = object : Callback() {\n" + kt_function("g", 1) + "  }\n}\n")
        self.assertEqual(cl.brace_functions(src, "kt"), [(2, 4), (7, 3)])

    def test_kotlin_one_line_data_class_before_a_function(self):
        # Regression: the data class and the fun share one header; the fun must still be measured.
        src = "class C {\n  data class E(val id: String)\n\n" + kt_function("scan", 59) + "}\n"
        self.assertEqual(cl.brace_functions(src, "kt"), [(4, 61)])

    def test_kotlin_raw_string_with_braces(self):
        src = 'fun f() {\n  val s = """\n }}\n"""\n}\n'
        self.assertEqual(cl.brace_functions(src, "kt"), [(1, 5)])

    def test_python_functions(self):
        src = "def f():\n" + "    x = 1\n" * 60 + "\n"
        self.assertEqual(cl.python_functions(src), [(1, 61)])


class FileRules(unittest.TestCase):
    def check(self, rel: str, text: str):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            return [v.rule for v in cl.check_file(p, rel)]

    def test_file_line_limit_boundary(self):
        self.assertEqual(self.check("a.py", "x = 1\n" * 400), [])
        self.assertEqual(self.check("a.py", "x = 1\n" * 401), ["file-lines"])

    def test_long_function_reported(self):
        self.assertEqual(self.check("a.cpp", cpp_function("f", 59)), ["function-lines"])

    def test_core_purity_only_applies_under_core(self):
        jni = "#include <jni.h>\n"
        self.assertEqual(self.check("core/x/a.cpp", jni), ["core-purity"])
        self.assertEqual(self.check("android/x/a.cpp", jni), [])
        kt = "package p\nimport android.util.Log\n"
        self.assertEqual(self.check("android/probe/src/main/java/core/A.kt", kt), ["core-purity"])


class Main(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cl.main([d]), 0)
            Path(d, "big.py").write_text("x = 1\n" * 500, encoding="utf-8")
            self.assertEqual(cl.main([d, "--json"]), 1)
            self.assertEqual(cl.main([str(Path(d) / "missing")]), 2)


if __name__ == "__main__":
    unittest.main()
