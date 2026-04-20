"""
공구 라이브러리 로드/파싱 서비스

사용자 편집용 YAML 공구 파일과
현장식 shorthand 입력(`T5 = 16mm REM`)을 함께 지원합니다.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List

import yaml

from app.models.tool import Tool
from app.utils.logger import get_logger

logger = get_logger("tool_library_service")

_TOOL_LINE_RE = re.compile(
    r"^\s*T(?P<tool_number>\d+)\s*=\s*(?P<diameter>\d+(?:\.\d+)?)\s*mm\s*(?P<tool_type>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+(?P<rest>.*))?$",
    re.IGNORECASE,
)


class ToolLibraryService:
    """공구 라이브러리 파일과 shorthand 입력을 `Tool` 객체로 변환합니다."""

    def load_file(self, filepath: str) -> Dict[int, Tool]:
        """YAML 공구 라이브러리 파일을 로드합니다."""

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"공구 라이브러리 파일을 찾을 수 없습니다: {filepath}")

        with open(filepath, "r", encoding="utf-8") as file:
            payload = yaml.safe_load(file) or {}

        base_dir = os.path.dirname(os.path.abspath(filepath))
        tools = self.load_payload(payload, base_dir=base_dir, source=filepath)
        logger.info("공구 라이브러리 로드 완료: %s (%d개)", filepath, len(tools))
        return tools

    def load_payload(
        self,
        payload: dict,
        base_dir: str = "",
        source: str = "",
    ) -> Dict[int, Tool]:
        """
        YAML payload에서 공구 정의를 읽어옵니다.

        지원 형식:
        - `tools: [...]`
        - `definitions: [...]`
        - `tool_library: { file, tools, definitions }`
        """

        merged: Dict[int, Tool] = {}

        library_cfg = payload.get("tool_library", {}) or {}
        nested_file = library_cfg.get("file")
        if nested_file:
            resolved = nested_file
            if base_dir and not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(base_dir, resolved))
            merged.update(self.load_file(resolved))

        direct_entries: List[object] = []
        for key in ("definitions", "tools"):
            value = payload.get(key)
            if isinstance(value, list):
                direct_entries.extend(value)

        for key in ("definitions", "tools"):
            value = library_cfg.get(key)
            if isinstance(value, list):
                direct_entries.extend(value)

        if direct_entries:
            merged.update(self.load_entries(direct_entries, source=source or "<payload>"))

        return merged

    def load_entries(self, entries: Iterable[object], source: str = "") -> Dict[int, Tool]:
        """문자열/딕셔너리 공구 정의 목록을 로드합니다."""

        tools: Dict[int, Tool] = {}
        for index, entry in enumerate(entries):
            try:
                tool = self.parse_entry(entry)
                tools[tool.tool_number] = tool
            except Exception as exc:
                logger.warning(
                    "공구 정의 파싱 실패: source=%s, index=%d, entry=%r, error=%s",
                    source or "<memory>",
                    index,
                    entry,
                    exc,
                )
        return tools

    def build_payload(
        self,
        tools: Dict[int, Tool] | Iterable[Tool],
        source_note: str = "",
    ) -> dict:
        """공구 라이브러리를 YAML 저장용 payload로 변환합니다."""

        if isinstance(tools, dict):
            tool_items = list(tools.values())
        else:
            tool_items = list(tools)

        ordered = sorted(tool_items, key=lambda tool: int(tool.tool_number))
        payload = {
            "tools": [tool.to_dict() for tool in ordered],
        }
        if source_note:
            payload["notes"] = str(source_note)
        return payload

    def save_file(
        self,
        filepath: str,
        tools: Dict[int, Tool] | Iterable[Tool],
        source_note: str = "",
    ) -> None:
        """공구 라이브러리를 YAML 파일로 저장합니다."""

        target = os.path.abspath(filepath)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        payload = self.build_payload(tools, source_note=source_note)

        with open(target, "w", encoding="utf-8") as file:
            yaml.safe_dump(
                payload,
                file,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )

        tool_count = len(payload.get("tools", []))
        logger.info("공구 라이브러리 저장 완료: %s (%d개)", target, tool_count)

    def parse_entry(self, entry: object) -> Tool:
        """단일 공구 정의를 `Tool` 객체로 변환합니다."""

        if isinstance(entry, Tool):
            return entry
        if isinstance(entry, str):
            return Tool.from_dict(self.parse_shorthand(entry))
        if isinstance(entry, dict):
            return Tool.from_dict(entry)
        raise TypeError(f"지원하지 않는 공구 정의 형식입니다: {type(entry)!r}")

    def parse_shorthand(self, text: str) -> dict:
        """
        shorthand 입력을 딕셔너리로 변환합니다.

        예:
        - `T5 = 16mm REM`
        - `T6 = 12mm EM 4F OH48 L85 RIGID=1.05 KC=0.95`
        - `T7 = 7.5mm DR 2F OH70 KTC=950 KAE=6`
        """

        normalized = text.strip()
        match = _TOOL_LINE_RE.match(normalized)
        if not match:
            raise ValueError(f"shorthand 공구 정의를 해석할 수 없습니다: {text}")

        data = {
            "tool_number": int(match.group("tool_number")),
            "diameter_mm": float(match.group("diameter")),
            "tool_type": match.group("tool_type").upper(),
            "tool_category": match.group("tool_type").upper(),
        }

        rest = (match.group("rest") or "").replace(",", " ")
        overrides = {}
        for token in [item for item in rest.split() if item]:
            upper = token.upper()
            numeric = self._parse_suffix_number(upper)

            if upper.endswith("F") and numeric is not None:
                data["flute_count"] = int(round(numeric))
                continue
            if upper.startswith("Z") and upper[1:].replace(".", "", 1).isdigit():
                data["flute_count"] = int(round(float(upper[1:])))
                continue
            if upper.startswith("OH") and upper[2:].replace(".", "", 1).isdigit():
                data["overhang_mm"] = float(upper[2:])
                continue
            if upper.startswith("L") and upper[1:].replace(".", "", 1).isdigit():
                data["length_mm"] = float(upper[1:])
                continue
            if upper.startswith("FL") and upper[2:].replace(".", "", 1).isdigit():
                data["flute_length_mm"] = float(upper[2:])
                continue
            if upper.startswith("RIGID="):
                data["rigidity_factor"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("KC="):
                data["cutting_coefficient_factor"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("KTC="):
                overrides["Ktc"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("KRC="):
                overrides["Krc"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("KAC="):
                overrides["Kac"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("KTE="):
                overrides["Kte"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("KRE="):
                overrides["Kre"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("KAE="):
                overrides["Kae"] = float(upper.split("=", 1)[1])
                continue
            if upper.startswith("NOTE="):
                data["notes"] = token.split("=", 1)[1]
                continue

        if overrides:
            data["material_coefficient_overrides"] = overrides

        return data

    @staticmethod
    def merge_tools(*libraries: Dict[int, Tool]) -> Dict[int, Tool]:
        """여러 공구 라이브러리를 순서대로 병합합니다."""

        merged: Dict[int, Tool] = {}
        for library in libraries:
            merged.update(library)
        return merged

    @staticmethod
    def _parse_suffix_number(token: str) -> float | None:
        """`4F` 같은 suffix 숫자를 읽습니다."""

        number_text = token[:-1]
        if not number_text:
            return None
        try:
            return float(number_text)
        except ValueError:
            return None
