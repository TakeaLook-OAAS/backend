"""
테스트 결과 PDF 리포트 생성기
tests/report.json 을 읽어 tests/test_report.pdf 를 생성합니다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from datetime import datetime, timezone
from fpdf import FPDF

FONT_PATH    = os.path.expanduser("~/Library/Fonts/malgun.ttf")
JSON_PATH    = os.path.join(os.path.dirname(__file__), "report.json")
OUTPUT_PATH  = os.path.join(os.path.dirname(__file__), "test_report.pdf")

# 테스트 그룹 표시명 매핑
GROUP_LABELS = {
    "TestBuildAggCounts": "_build_agg_counts() 단위 테스트",
    "TestPostEvents":     "POST /events/ API 테스트",
    "TestAggregation":    "집계 로직 (DailyAgg) 테스트",
    "TestGetEvents":      "GET /events/ 조회 테스트",
}

# 파일명 표시명 매핑
FILE_LABELS = {
    "tests/test_aggregation_unit.py": "test_aggregation_unit.py",
    "tests/test_full_flow.py":        "test_full_flow.py",
}

# 상태별 색상 (R, G, B)
COLOR_PASS    = (34, 139, 34)
COLOR_FAIL    = (200, 30, 30)
COLOR_WARN    = (200, 140, 0)
COLOR_HEADER  = (30, 60, 120)
COLOR_SUBHEAD = (60, 100, 180)
COLOR_ROW_ALT = (240, 244, 252)
COLOR_ROW_NRM = (255, 255, 255)
COLOR_BORDER  = (180, 190, 210)


def load_report(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_groups(tests: list) -> dict:
    """테스트 목록을 그룹(클래스)별로 분류."""
    groups: dict[str, list] = {}
    for t in tests:
        node = t["nodeid"]          # e.g. tests/test_full_flow.py::TestAggregation::test_xxx
        parts = node.split("::")
        if len(parts) == 3:
            file_part, cls, name = parts
        else:
            file_part, cls, name = parts[0], "기타", parts[-1]
        key = (file_part, cls)
        groups.setdefault(key, []).append({
            "name":     name,
            "outcome":  t["outcome"],
            "duration": t.get("duration", 0),
        })
    return groups


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("KR", style="",  fname=FONT_PATH)
        self.add_font("KR", style="B", fname=FONT_PATH)
        self.set_auto_page_break(auto=True, margin=18)

    # ── 헤더 / 푸터 ──────────────────────────────────────────────────────────

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("KR", "B", 8)
        self.set_text_color(130, 140, 160)
        self.cell(0, 6, "OAAS 백엔드 테스트 결과 보고서", align="L")
        self.ln(0.5)
        self.set_draw_color(*COLOR_BORDER)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("KR", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, f"{self.page_no()} 페이지", align="C")

    # ── 표지 ──────────────────────────────────────────────────────────────────

    def cover_page(self, report: dict):
        self.add_page()
        # 상단 배경 띠
        self.set_fill_color(*COLOR_HEADER)
        self.rect(0, 0, self.w, 58, style="F")

        self.set_y(14)
        self.set_font("KR", "B", 20)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, "OAAS 백엔드 테스트 결과 보고서", align="C")
        self.ln(10)
        self.set_font("KR", "", 11)
        self.cell(0, 8, "Offline Ad Analysis Service", align="C")
        self.ln(24)

        # 요약 박스
        summary = report["summary"]
        total   = summary.get("total",   0)
        passed  = summary.get("passed",  0)
        failed  = summary.get("failed",  0)
        warn    = summary.get("warnings", 0)
        dur     = report.get("duration", 0)
        created = datetime.now(timezone.utc).strftime("%Y년 %m월 %d일  %H:%M UTC")

        self.set_fill_color(248, 250, 255)
        self.set_draw_color(*COLOR_BORDER)
        self.set_line_width(0.4)
        box_x = self.l_margin
        box_w = self.w - self.l_margin - self.r_margin
        self.rect(box_x, self.get_y(), box_w, 54, style="FD")

        self.set_y(self.get_y() + 6)
        self._summary_row("생성 일시",  created)
        self._summary_row("테스트 환경", "Python 3.13.3  /  pytest 9.0.2  /  macOS 15.5 arm64")
        self._summary_row("대상 모듈",  "events.py  /  Aggregation.py")
        self._summary_row("총 실행 시간", f"{dur:.2f} 초")
        self.ln(3)
        self._summary_row("전체 테스트",   str(total),  bold_value=True)

        # 합격/불합격 수치
        y = self.get_y()
        self.set_xy(box_x + 6, y)
        self.set_font("KR", "", 10)
        self.set_text_color(80, 80, 80)
        self.cell(38, 7, "결과")
        self.set_font("KR", "B", 10)
        self.set_text_color(*COLOR_PASS)
        self.cell(30, 7, f"PASS  {passed}")
        if failed:
            self.set_text_color(*COLOR_FAIL)
            self.cell(30, 7, f"FAIL  {failed}")
        if warn:
            self.set_text_color(*COLOR_WARN)
            self.cell(30, 7, f"경고  {warn}")
        self.ln(14)

    def _summary_row(self, label: str, value: str, bold_value: bool = False):
        self.set_x(self.l_margin + 6)
        self.set_font("KR", "", 10)
        self.set_text_color(100, 110, 130)
        self.cell(44, 7, label)
        style = "B" if bold_value else ""
        self.set_font("KR", style, 10)
        self.set_text_color(30, 30, 30)
        self.cell(0, 7, value)
        self.ln()

    # ── 그룹 섹션 ─────────────────────────────────────────────────────────────

    def section_header(self, file_label: str, cls: str, tests: list):
        passed = sum(1 for t in tests if t["outcome"] == "passed")
        total  = len(tests)
        label  = GROUP_LABELS.get(cls, cls)

        self.ln(4)
        self.set_fill_color(*COLOR_SUBHEAD)
        self.set_text_color(255, 255, 255)
        self.set_font("KR", "B", 10)
        self.set_x(self.l_margin)
        self.cell(0, 8, f"  {label}", fill=True)
        self.ln()

        self.set_font("KR", "", 8)
        self.set_text_color(120, 130, 150)
        self.set_x(self.l_margin)
        self.cell(0, 5, f"  {file_label}  ·  {passed}/{total} passed")
        self.ln(6)

    def test_table(self, tests: list):
        col_w   = [10, 118, 28, 24]   # #, 테스트명, 소요시간, 결과
        headers = ["#", "테스트 항목", "소요(s)", "결과"]

        # 컬럼 헤더
        self.set_fill_color(220, 228, 245)
        self.set_text_color(40, 50, 80)
        self.set_font("KR", "B", 8.5)
        self.set_draw_color(*COLOR_BORDER)
        self.set_line_width(0.2)
        self.set_x(self.l_margin)
        for w, h in zip(col_w, headers):
            self.cell(w, 7, h, border=1, fill=True, align="C")
        self.ln()

        for i, t in enumerate(tests):
            fill_color = COLOR_ROW_ALT if i % 2 == 0 else COLOR_ROW_NRM
            self.set_fill_color(*fill_color)
            outcome = t["outcome"]
            dur     = t["duration"]
            name    = t["name"].replace("_", " ")

            self.set_x(self.l_margin)
            self.set_font("KR", "", 8.5)
            self.set_text_color(80, 80, 80)

            # # 번호
            self.cell(col_w[0], 6.5, str(i + 1), border=1, fill=True, align="C")
            # 테스트명
            self.cell(col_w[1], 6.5, f" {name}", border=1, fill=True)
            # 소요시간
            self.cell(col_w[2], 6.5, f"{dur:.3f}", border=1, fill=True, align="R")
            # 결과
            if outcome == "passed":
                self.set_text_color(*COLOR_PASS)
                label = "PASS"
            elif outcome == "failed":
                self.set_text_color(*COLOR_FAIL)
                label = "FAIL"
            else:
                self.set_text_color(*COLOR_WARN)
                label = outcome.upper()
            self.set_font("KR", "B", 8.5)
            self.cell(col_w[3], 6.5, label, border=1, fill=True, align="C")
            self.set_text_color(80, 80, 80)
            self.ln()

    # ── 최종 요약 페이지 ──────────────────────────────────────────────────────

    def summary_page(self, report: dict, groups: dict):
        self.add_page()
        self.set_font("KR", "B", 13)
        self.set_text_color(*COLOR_HEADER)
        self.cell(0, 10, "테스트 결과 종합", align="C")
        self.ln(12)

        # 그룹별 통계 테이블
        col_w   = [74, 22, 22, 22, 40]
        headers = ["테스트 그룹", "전체", "PASS", "FAIL", "소요(s)"]

        self.set_fill_color(220, 228, 245)
        self.set_text_color(40, 50, 80)
        self.set_font("KR", "B", 9)
        self.set_draw_color(*COLOR_BORDER)
        self.set_line_width(0.2)
        self.set_x(self.l_margin)
        for w, h in zip(col_w, headers):
            self.cell(w, 7, h, border=1, fill=True, align="C")
        self.ln()

        for i, ((file_part, cls), tests) in enumerate(groups.items()):
            total  = len(tests)
            passed = sum(1 for t in tests if t["outcome"] == "passed")
            failed = total - passed
            dur    = sum(t["duration"] for t in tests)
            label  = GROUP_LABELS.get(cls, cls)
            fill   = COLOR_ROW_ALT if i % 2 == 0 else COLOR_ROW_NRM

            self.set_fill_color(*fill)
            self.set_text_color(50, 50, 50)
            self.set_font("KR", "", 9)
            self.set_x(self.l_margin)
            self.cell(col_w[0], 7, f" {label}", border=1, fill=True)
            self.cell(col_w[1], 7, str(total),  border=1, fill=True, align="C")
            if failed == 0:
                self.set_text_color(*COLOR_PASS)
            self.set_font("KR", "B", 9)
            self.cell(col_w[2], 7, str(passed), border=1, fill=True, align="C")
            if failed:
                self.set_text_color(*COLOR_FAIL)
                self.cell(col_w[3], 7, str(failed), border=1, fill=True, align="C")
            else:
                self.set_text_color(180, 180, 180)
                self.set_font("KR", "", 9)
                self.cell(col_w[3], 7, "-", border=1, fill=True, align="C")
            self.set_text_color(80, 80, 80)
            self.set_font("KR", "", 9)
            self.cell(col_w[4], 7, f"{dur:.3f}", border=1, fill=True, align="R")
            self.ln()

        # 합계 행
        summary  = report["summary"]
        total_all = summary.get("total",  0)
        pass_all  = summary.get("passed", 0)
        fail_all  = summary.get("failed", 0)
        dur_all   = report.get("duration", 0)

        self.set_fill_color(210, 220, 240)
        self.set_text_color(30, 30, 80)
        self.set_font("KR", "B", 9)
        self.set_x(self.l_margin)
        self.cell(col_w[0], 7, " 합계", border=1, fill=True)
        self.cell(col_w[1], 7, str(total_all), border=1, fill=True, align="C")
        self.set_text_color(*COLOR_PASS)
        self.cell(col_w[2], 7, str(pass_all),  border=1, fill=True, align="C")
        self.set_text_color(*COLOR_FAIL if fail_all else (180, 180, 180))
        self.cell(col_w[3], 7, str(fail_all) if fail_all else "-", border=1, fill=True, align="C")
        self.set_text_color(30, 30, 80)
        self.cell(col_w[4], 7, f"{dur_all:.3f}", border=1, fill=True, align="R")
        self.ln(14)

        # 최종 판정
        verdict = "전체 테스트 통과 (ALL PASS)" if fail_all == 0 else f"실패 테스트 {fail_all}건 존재"
        color   = COLOR_PASS if fail_all == 0 else COLOR_FAIL
        self.set_fill_color(*color)
        self.set_text_color(255, 255, 255)
        self.set_font("KR", "B", 12)
        self.set_x(self.l_margin)
        self.cell(0, 12, f"  최종 판정:  {verdict}", fill=True)


def generate(json_path: str, output_path: str):
    report = load_report(json_path)
    groups = parse_groups(report["tests"])

    pdf = ReportPDF()
    pdf.cover_page(report)

    # 그룹별 상세 페이지
    for (file_part, cls), tests in groups.items():
        pdf.add_page()
        file_label = FILE_LABELS.get(file_part, file_part)
        pdf.section_header(file_label, cls, tests)
        pdf.test_table(tests)

    # 종합 요약 페이지
    pdf.summary_page(report, groups)

    pdf.output(output_path)
    print(f"PDF 생성 완료: {output_path}")


if __name__ == "__main__":
    generate(JSON_PATH, OUTPUT_PATH)
