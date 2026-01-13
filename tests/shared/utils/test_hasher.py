import unittest
import hashlib
from warden.shared.utils.hasher import NormalizedHasher
from warden.ast.domain.enums import CodeLanguage

class TestNormalizedHasher(unittest.TestCase):
    def test_normalization_ignores_whitespace(self):
        code1 = "def foo():\n    pass\n"
        code2 = "def foo():\n\tpass\n\n\n"
        
        hash1 = NormalizedHasher.calculate_normalized_hash(code1, CodeLanguage.PYTHON)
        hash2 = NormalizedHasher.calculate_normalized_hash(code2, CodeLanguage.PYTHON)
        
        self.assertEqual(hash1, hash2)

    def test_normalization_ignores_python_comments(self):
        code1 = "def foo():\n    pass"
        code2 = "def foo():\n    # This is a comment\n    pass"
        
        hash1 = NormalizedHasher.calculate_normalized_hash(code1, CodeLanguage.PYTHON)
        hash2 = NormalizedHasher.calculate_normalized_hash(code2, CodeLanguage.PYTHON)
        
        self.assertEqual(hash1, hash2)

    def test_normalization_ignores_c_comments(self):
        code1 = "void foo() { return; }"
        code2 = "/* multi line\n   comment */\nvoid foo() {\n  // single line\n  return;\n}"
        
        hash1 = NormalizedHasher.calculate_normalized_hash(code1, CodeLanguage.JAVASCRIPT)
        hash2 = NormalizedHasher.calculate_normalized_hash(code2, CodeLanguage.JAVASCRIPT)
        
        self.assertEqual(hash1, hash2)

    def test_normalization_ignores_html_comments(self):
        code1 = "<div>Hello</div>"
        code2 = "<!-- comment -->\n<div>\n  Hello\n</div>"
        
        hash1 = NormalizedHasher.calculate_normalized_hash(code1, CodeLanguage.HTML)
        hash2 = NormalizedHasher.calculate_normalized_hash(code2, CodeLanguage.HTML)
        
        self.assertEqual(hash1, hash2)

    def test_different_code_different_hash(self):
        code1 = "def foo(): pass"
        code2 = "def bar(): pass"
        
        hash1 = NormalizedHasher.calculate_normalized_hash(code1, CodeLanguage.PYTHON)
        hash2 = NormalizedHasher.calculate_normalized_hash(code2, CodeLanguage.PYTHON)
        
        self.assertNotEqual(hash1, hash2)
