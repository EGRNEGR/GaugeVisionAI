"""
GaugeVision AI — генератор корпоративных документов Microsoft Word (.docx) без внешних зависимостей.

Формирует валидный OpenXML-архив (.docx), совместимый с Microsoft Word и LibreOffice:
  • корпоративный колонтитул с нумерацией страниц (header1.xml / footer1.xml);
  • штамп утверждения / реквизитов документа;
  • заголовки уровней 1–3, абзацы, маркированные списки, инфо-врезки (callout);
  • таблицы с корпоративной шапкой (#1F3864), границами, чередованием строк и переносом заголовка;
  • встроенные изображения (JPEG/PNG) через DrawingML (<w:drawing>) с подписями рисунков.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
from xml.sax.saxutils import escape as _raw_xml_escape

_XML_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def xml_escape(text: str) -> str:
    """Экранирует спецсимволы XML и удаляет недопустимые в XML 1.0 управляющие байты."""
    return _raw_xml_escape(_XML_CTRL_RE.sub("", str(text)))

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Извлекает (width, height) из заголовка JPEG/PNG без сторонних библиотек."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return max(1, w), max(1, h)
    # JPEG SOF parser
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return max(1, w), max(1, h)
        if marker in (0xD8, 0xD9, 0x01) or (0xD0 <= marker <= 0xD7):
            i += 2
        else:
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + max(2, seg_len)
    return 640, 480


class DocxBuilder:
    """Сборщик корпоративного .docx документа (OpenXML)."""

    def __init__(self, *, doc_title: str, header_text: str, footer_left: str) -> None:
        self.doc_title = doc_title
        self.header_text = header_text
        self.footer_left = footer_left
        self._body_xml: list[str] = []
        self._images: list[tuple[str, str, bytes]] = []  # (rid, filename, bytes)
        self._next_img_id = 1

    def add_title_block(self, *, org_line: str, doc_kind: str, title: str, subtitle: str,
                        doc_number: str, date_str: str) -> None:
        self._body_xml.append(
            f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="60"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:b/><w:sz w:val="20"/><w:color w:val="334155"/></w:rPr>'
            f'<w:t>{xml_escape(org_line)}</w:t></w:r></w:p>'
        )
        # Таблица-штамп утверждения (две колонки: СОГЛАСОВАНО / УТВЕРЖДАЮ)
        stamp_rows = [
            ["СОГЛАСОВАНО", "УТВЕРЖДАЮ"],
            ["Начальник цеха КИПиА и АСУ ТП\n____________________ / ____________ /\n«___» ______________ 202_ г.",
             "Главный инженер энергообъекта\n____________________ / ____________ /\n«___» ______________ 202_ г."],
        ]
        self.add_table(stamp_rows, col_widths_dxa=[4600, 4600], header_bg="F1F5F9", header_fg="1E293B", border_color="94A3B8")
        self._body_xml.append('<w:p><w:pPr><w:spacing w:before="140" w:after="40"/></w:pPr></w:p>')

        self._body_xml.append(
            f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="80" w:after="40"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:b/><w:sz w:val="24"/><w:color w:val="1F3864"/></w:rPr>'
            f'<w:t>{xml_escape(doc_kind.upper())}</w:t></w:r></w:p>'
        )
        self._body_xml.append(
            f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="20" w:after="60"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:b/><w:sz w:val="30"/><w:color w:val="0F172A"/></w:rPr>'
            f'<w:t>{xml_escape(title)}</w:t></w:r></w:p>'
        )
        self._body_xml.append(
            f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="100"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:sz w:val="20"/><w:color w:val="475569"/></w:rPr>'
            f'<w:t>{xml_escape(subtitle)}</w:t></w:r></w:p>'
        )
        self._body_xml.append(
            f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="180"/>'
            f'<w:pBdr><w:bottom w:val="single" w:sz="12" w:space="6" w:color="1F3864"/></w:pBdr></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:b/><w:sz w:val="19"/><w:color w:val="1F3864"/></w:rPr>'
            f'<w:t>{xml_escape(f"Документ № {doc_number}   |   Дата формирования: {date_str}")}</w:t></w:r></w:p>'
        )

    def add_heading(self, text: str, level: int = 1) -> None:
        sz = {1: 26, 2: 22, 3: 20}.get(level, 20)
        color = "1F3864" if level == 1 else "1E3A5F"
        before = 220 if level == 1 else 140
        border = '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="3" w:color="CBD5E1"/></w:pBdr>' if level == 1 else ""
        self._body_xml.append(
            f'<w:p><w:pPr><w:keepNext/><w:spacing w:before="{before}" w:after="80"/>{border}</w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:b/><w:sz w:val="{sz}"/><w:color w:val="{color}"/></w:rPr>'
            f'<w:t>{xml_escape(text)}</w:t></w:r></w:p>'
        )

    def add_paragraph(self, text: str, *, bold: bool = False, italic: bool = False,
                      color: str = "1E293B", size_half_pt: int = 20, space_after: int = 80) -> None:
        b_tag = "<w:b/>" if bold else ""
        i_tag = "<w:i/>" if italic else ""
        self._body_xml.append(
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="{space_after}" w:line="264" w:lineRule="auto"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'{b_tag}{i_tag}<w:sz w:val="{size_half_pt}"/><w:color w:val="{color}"/></w:rPr>'
            f'<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>'
        )

    def add_bullet(self, lead: str, text: str) -> None:
        self._body_xml.append(
            f'<w:p><w:pPr><w:ind w:left="360" w:hanging="180"/>'
            f'<w:spacing w:before="0" w:after="50" w:line="252" w:lineRule="auto"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:b/><w:sz w:val="19"/><w:color w:val="1F3864"/></w:rPr>'
            f'<w:t xml:space="preserve">• {xml_escape(lead)}</w:t></w:r>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:sz w:val="19"/><w:color w:val="1E293B"/></w:rPr>'
            f'<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>'
        )

    def add_callout(self, title: str, text: str, *, fill: str = "EEF2F7", accent: str = "1F3864") -> None:
        self._body_xml.append(
            f'<w:tbl><w:tblPr><w:tblW w:w="9200" w:type="dxa"/>'
            f'<w:tblBorders>'
            f'<w:top w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
            f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
            f'<w:right w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
            f'<w:left w:val="single" w:sz="24" w:space="0" w:color="{accent}"/>'
            f'</w:tblBorders></w:tblPr>'
            f'<w:tr><w:tc><w:tcPr><w:tcW w:w="9200" w:type="dxa"/>'
            f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
            f'<w:tcMar><w:top w:w="100" w:type="dxa"/><w:bottom w:w="100" w:type="dxa"/>'
            f'<w:left w:w="160" w:type="dxa"/><w:right w:w="140" w:type="dxa"/></w:tcMar></w:tcPr>'
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="40"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:b/><w:sz w:val="19"/><w:color w:val="{accent}"/></w:rPr>'
            f'<w:t>{xml_escape(title)}</w:t></w:r></w:p>'
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="252" w:lineRule="auto"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:sz w:val="18"/><w:color w:val="1E293B"/></w:rPr>'
            f'<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>'
            f'</w:tc></w:tr></w:tbl>'
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="60"/></w:pPr></w:p>'
        )

    def add_table(
        self,
        rows: list[list[str]],
        *,
        col_widths_dxa: list[int] | None = None,
        header_bg: str = "1F3864",
        header_fg: str = "FFFFFF",
        border_color: str = "CBD5E1",
        font_half_pt: int = 17,
    ) -> None:
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        if not col_widths_dxa or len(col_widths_dxa) != ncols:
            w = 9200 // max(1, ncols)
            col_widths_dxa = [w] * ncols
        total_w = sum(col_widths_dxa)
        grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in col_widths_dxa)
        tr_parts: list[str] = []
        for r_idx, row in enumerate(rows):
            is_hdr = r_idx == 0
            bg = header_bg if is_hdr else ("F8FAFC" if r_idx % 2 == 0 else "FFFFFF")
            fg = header_fg if is_hdr else "0F172A"
            tr_pr = '<w:trPr><w:cantSplit/>' + ('<w:tblHeader/>' if is_hdr else '') + '</w:trPr>'
            tc_parts: list[str] = []
            for c_idx in range(ncols):
                cell_txt = str(row[c_idx]) if c_idx < len(row) else ""
                lines = cell_txt.split("\n")
                p_xml = []
                for ln in lines:
                    p_xml.append(
                        f'<w:p><w:pPr><w:spacing w:before="10" w:after="10" w:line="228" w:lineRule="auto"/></w:pPr>'
                        f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
                        f'{"<w:b/>" if is_hdr else ""}<w:sz w:val="{font_half_pt}"/><w:color w:val="{fg}"/></w:rPr>'
                        f'<w:t xml:space="preserve">{xml_escape(ln)}</w:t></w:r></w:p>'
                    )
                tc_parts.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{col_widths_dxa[c_idx]}" w:type="dxa"/>'
                    f'<w:shd w:val="clear" w:color="auto" w:fill="{bg}"/>'
                    f'<w:tcMar><w:top w:w="60" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/>'
                    f'<w:left w:w="90" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tcMar>'
                    f'<w:vAlign w:val="center"/></w:tcPr>{"".join(p_xml)}</w:tc>'
                )
            tr_parts.append(f'<w:tr>{tr_pr}{"".join(tc_parts)}</w:tr>')

        self._body_xml.append(
            f'<w:tbl><w:tblPr><w:tblW w:w="{total_w}" w:type="dxa"/>'
            f'<w:tblBorders>'
            f'<w:top w:val="single" w:sz="6" w:space="0" w:color="{border_color}"/>'
            f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="{border_color}"/>'
            f'<w:left w:val="single" w:sz="4" w:space="0" w:color="{border_color}"/>'
            f'<w:right w:val="single" w:sz="4" w:space="0" w:color="{border_color}"/>'
            f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{border_color}"/>'
            f'<w:insideV w:val="single" w:sz="4" w:space="0" w:color="{border_color}"/>'
            f'</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{"".join(tr_parts)}</w:tbl>'
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="80"/></w:pPr></w:p>'
        )

    def add_image(self, img_bytes: bytes, caption: str, *, width_cm: float = 13.8) -> None:
        if not img_bytes:
            return
        idx = self._next_img_id
        self._next_img_id += 1
        ext = "png" if img_bytes.startswith(b"\x89PNG") else "jpg"
        rid = f"rIdImg{idx}"
        fname = f"media/image{idx}.{ext}"
        self._images.append((rid, fname, img_bytes))

        px_w, px_h = _jpeg_dimensions(img_bytes)
        cx = int(width_cm * 360000)  # 1 cm = 360000 EMU
        cy = int(cx * (px_h / max(1, px_w)))
        # Ограничиваем высоту изображения, чтобы аккуратно помещалось на страницу A4
        max_cy = int(10.5 * 360000)
        if cy > max_cy:
            scale = max_cy / cy
            cy = max_cy
            cx = int(cx * scale)

        self._body_xml.append(
            f'<w:p><w:pPr><w:jc w:val="center"/><w:keepNext/><w:spacing w:before="80" w:after="40"/></w:pPr>'
            f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{idx}" name="EvidenceFrame{idx}"/>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{idx}" name="{fname}"/>'
            f'<pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
        )
        self._body_xml.append(
            f'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="120"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            f'<w:i/><w:sz w:val="17"/><w:color w:val="475569"/></w:rPr>'
            f'<w:t>{xml_escape(caption)}</w:t></w:r></w:p>'
        )

    def build_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", self._content_types_xml())
            zf.writestr("_rels/.rels", self._root_rels_xml())
            zf.writestr("word/document.xml", self._document_xml())
            zf.writestr("word/styles.xml", self._styles_xml())
            zf.writestr("word/header1.xml", self._header_xml())
            zf.writestr("word/footer1.xml", self._footer_xml())
            zf.writestr("word/_rels/document.xml.rels", self._document_rels_xml())
            for _, fname, raw in self._images:
                zf.writestr(f"word/{fname}", raw)
        return buf.getvalue()

    def _content_types_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="jpg" ContentType="image/jpeg"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '</Types>'
        )

    def _root_rels_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>'
        )

    def _document_rels_xml(self) -> str:
        rels = [
            '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
            '<Relationship Id="rIdHdr" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>',
            '<Relationship Id="rIdFtr" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>',
        ]
        for rid, fname, _ in self._images:
            rels.append(
                f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{fname}"/>'
            )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels)
            + '</Relationships>'
        )

    def _styles_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:styles xmlns:w="{W_NS}">'
            '<w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            '<w:sz w:val="20"/><w:lang w:val="ru-RU"/>'
            '</w:rPr></w:rPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            '<w:name w:val="Normal"/></w:style>'
            '</w:styles>'
        )

    def _header_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:hdr xmlns:w="{W_NS}">'
            '<w:p><w:pPr><w:jc w:val="right"/>'
            '<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="2" w:color="CBD5E1"/></w:pBdr></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            '<w:sz w:val="16"/><w:color w:val="64748B"/></w:rPr>'
            f'<w:t>{xml_escape(self.header_text)}</w:t></w:r></w:p></w:hdr>'
        )

    def _footer_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:ftr xmlns:w="{W_NS}">'
            '<w:p><w:pPr><w:pBdr><w:top w:val="single" w:sz="4" w:space="2" w:color="CBD5E1"/></w:pBdr></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
            '<w:sz w:val="16"/><w:color w:val="64748B"/></w:rPr>'
            f'<w:t xml:space="preserve">{xml_escape(self.footer_left)}   |   Стр. </w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>1</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'
        )

    def _document_xml(self) -> str:
        # A4 portrait (11906 x 16838 dxa), поля: левое 2,2 см (1247), правое 1,6 см (907), верх/низ 1,8 см (1020)
        sect_pr = (
            '<w:sectPr>'
            '<w:headerReference w:type="default" r:id="rIdHdr"/>'
            '<w:footerReference w:type="default" r:id="rIdFtr"/>'
            '<w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1020" w:right="907" w:bottom="1020" w:left="1247" w:header="567" w:footer="567" w:gutter="0"/>'
            '</w:sectPr>'
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}" xmlns:wp="{WP_NS}" '
            f'xmlns:a="{A_NS}" xmlns:pic="{PIC_NS}">'
            f'<w:body>{"".join(self._body_xml)}{sect_pr}</w:body></w:document>'
        )
