from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True)
class WorkbookSheet:
    name: str
    rows: list[list[str]]


def _column_index(cell_ref: str) -> int:
    letters = []
    for char in cell_ref:
        if char.isalpha():
            letters.append(char)
        else:
            break

    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - 64)
    return max(index - 1, 0)


def _read_shared_strings(workbook_zip: ZipFile) -> list[str]:
    shared_strings_path = "xl/sharedStrings.xml"
    if shared_strings_path not in workbook_zip.namelist():
        return []

    root = ET.fromstring(workbook_zip.read(shared_strings_path))
    values: list[str] = []
    for item in root.findall("a:si", NS):
        text = "".join(node.text or "" for node in item.iterfind(".//a:t", NS))
        values.append(text)
    return values


def _read_sheet_targets(workbook_zip: ZipFile) -> list[tuple[str, str]]:
    workbook_root = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
    rels_root = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
    relationship_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_root.findall("p:Relationship", NS)
    }

    sheet_targets: list[tuple[str, str]] = []
    for sheet in workbook_root.findall("a:sheets/a:sheet", NS):
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = relationship_map[rel_id]
        sheet_targets.append((sheet.attrib["name"], f"xl/{target}"))
    return sheet_targets


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    value_node = cell.find("a:v", NS)
    inline_node = cell.find("a:is", NS)
    cell_type = cell.attrib.get("t")

    if cell_type == "s" and value_node is not None:
        try:
            return shared_strings[int(value_node.text or "0")]
        except (ValueError, IndexError):
            return value_node.text or ""

    if cell_type == "inlineStr" and inline_node is not None:
        return "".join(text_node.text or "" for text_node in inline_node.iterfind(".//a:t", NS))

    if value_node is not None:
        return value_node.text or ""

    return ""


def read_workbook_sheets(workbook_path: Path) -> list[WorkbookSheet]:
    with ZipFile(workbook_path) as workbook_zip:
        shared_strings = _read_shared_strings(workbook_zip)
        sheets = []
        for sheet_name, target in _read_sheet_targets(workbook_zip):
            root = ET.fromstring(workbook_zip.read(target))
            rows: list[list[str]] = []
            for row in root.findall(".//a:sheetData/a:row", NS):
                indexed_values: dict[int, str] = defaultdict(str)
                max_index = -1
                for cell in row.findall("a:c", NS):
                    cell_ref = cell.attrib.get("r", "A1")
                    index = _column_index(cell_ref)
                    indexed_values[index] = _read_cell_value(cell, shared_strings)
                    max_index = max(max_index, index)

                if max_index < 0:
                    rows.append([])
                    continue

                rows.append([indexed_values[index] for index in range(max_index + 1)])
            sheets.append(WorkbookSheet(name=sheet_name, rows=rows))
        return sheets


def read_workbook_sheet_map(workbook_path: Path) -> dict[str, WorkbookSheet]:
    return {sheet.name: sheet for sheet in read_workbook_sheets(workbook_path)}
