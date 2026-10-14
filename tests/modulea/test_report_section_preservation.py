"""报告局部替换必须保留纵横页的节断，避免富集页面误转横向。"""

import unittest
from docx import Document
from docx.enum.section import WD_SECTION, WD_ORIENT
from docx.oxml.ns import qn
from docx.shared import Cm
from science_modules.a07.commented_documents import clear_between, append_before


class SectionTests(unittest.TestCase):
    def test_replacing_enrichment_preserves_portrait_landscape_boundary(self):
        document = Document()
        start = document.add_heading("富集", level=1)
        document.add_paragraph("旧表旧图")
        section = document.add_section(WD_SECTION.NEW_PAGE)
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Cm(29.7), Cm(21)
        stop = document.add_heading("对接", level=1)
        boundary = clear_between(start, stop)
        self.assertIsNotNone(boundary)
        append_before(document, boundary, lambda: document.add_paragraph("新表新图"))
        self.assertEqual(len(document.sections), 2)
        self.assertLess(document.sections[0].page_width, document.sections[0].page_height)
        self.assertGreater(document.sections[1].page_width, document.sections[1].page_height)
        nodes = list(document._element.body)
        new = next(p for p in document.paragraphs if p.text == "新表新图")
        self.assertLess(nodes.index(new._p), nodes.index(boundary))
        self.assertNotIn("旧表旧图", [p.text for p in document.paragraphs])


if __name__ == "__main__":
    unittest.main()
