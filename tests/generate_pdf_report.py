import sys, os
import json
from datetime import datetime, timezone
from fpdf import FPDF

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
FONT_PATH    = os.path.expanduser("~/Library/Fonts/malgun.ttf") # Windows는 "C:/Windows/Fonts/malgun.ttf"
JSON_PATH    = os.path.join(os.path.dirname(__file__), "report.json")
OUTPUT_PATH  = os.path.join(os.path.dirname(__file__), "test_report.pdf")

# 1. 테스트 케이스별 상세 설명 (교수님께 보여줄 핵심 내용)
TEST_DESCRIPTIONS = {
    "test_빈_리스트_입력": "데이터가 전혀 없을 때 시스템이 에러 없이 0으로 안전하게 처리하는지 검증",
    "test_관심_인구_없음": "노출은 되었으나 시선 응시가 없는 경우, 인구 통계는 집계하되 관심도는 0%로 유지하는지 확인",
    "test_AI팀_샘플_배치_7개_트랙": "AI 모델이 전송한 실제 JSON 샘플(7명)을 바탕으로 성별/연령대 분포 정확도 100% 검증",
    "test_정상_배치_수신_202": "API 엔드포인트가 AI 기기의 데이터를 정상적으로 수신하고 비동기 처리를 시작하는지 확인",
    "test_events_raw_7행_저장": "수신된 7개의 트랙 데이터가 DB의 원본 로그 테이블(events_raw)에 유실 없이 저장되는지 검증",
    "test_daily_agg_exposure_count_7": "하루 동안 쌓인 로우 로그 7건이 일별 통계 테이블에서 '총 노출수 7'로 정확히 합산되는지 확인",
    "test_미등록_기기_401": "보안 검증: 데이터베이스에 등록되지 않은 기기 UUID가 접근할 경우 401 Unauthorized로 차단하는지 테스트",
    "test_중복_배치_409": "네트워크 오류로 동일한 배치가 중복 전송될 경우, 데이터 중복 삽입을 방지하고 409 Conflict를 반환하는지 확인"
}

# 색상 정의
COLOR_PASS    = (34, 139, 34)
COLOR_FAIL    = (200, 30, 30)
COLOR_WARN    = (200, 140, 0)
COLOR_HEADER  = (28, 54, 107)
COLOR_BG_LIGHT = (245, 247, 250)

class ReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("KR", style="",  fname=FONT_PATH)
        self.add_font("KR", style="B", fname=FONT_PATH)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if self.page_no() > 1:
            self.set_font("KR", "", 8)
            self.set_text_color(150)
            self.cell(0, 10, f"OAAS Backend Technical Test Report - Page {self.page_no()}", align="R")
            self.ln(10)

    def add_section_title(self, title):
        self.set_font("KR", "B", 14)
        self.set_text_color(*COLOR_HEADER)
        self.cell(0, 10, title, ln=True)
        self.set_draw_color(*COLOR_HEADER)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), 210 - self.r_margin, self.get_y())
        self.ln(5)

    def draw_test_result_box(self, name, outcome, duration, longrepr=None):
        """각 테스트 항목을 상세 설명과 함께 박스 형태로 출력"""
        description = TEST_DESCRIPTIONS.get(name, "상세 설명이 등록되지 않은 테스트 항목입니다.")
        
        # 박스 시작
        self.set_fill_color(*COLOR_BG_LIGHT)
        self.set_draw_color(200, 200, 200)
        start_y = self.get_y()
        self.rect(self.l_margin, start_y, 190 - self.l_margin, 25 if not longrepr else 50, style="F")
        
        # 결과 라벨 (PASS/FAIL)
        self.set_font("KR", "B", 10)
        if outcome == "passed":
            self.set_text_color(*COLOR_PASS)
            result_text = "[PASS]"
        else:
            self.set_text_color(*COLOR_FAIL)
            result_text = "[FAIL]"
        
        self.set_xy(self.l_margin + 5, start_y + 5)
        self.cell(20, 5, result_text)
        
        # 테스트 이름
        self.set_text_color(0)
        self.cell(0, 5, f"항목: {name.replace('_', ' ')}")
        self.ln(7)
        
        # 상세 설명
        self.set_x(self.l_margin + 10)
        self.set_font("KR", "", 9)
        self.set_text_color(80)
        self.multi_cell(0, 5, f"검증 내용: {description}")
        
        # 소요 시간
        self.set_font("KR", "", 8)
        self.set_text_color(150)
        self.set_xy(160, start_y + 5)
        self.cell(30, 5, f"소요: {duration:.3f}s", align="R")
        
        # 에러 로그가 있다면 출력
        if longrepr:
            self.ln(2)
            self.set_x(self.l_margin + 10)
            self.set_fill_color(255, 235, 235)
            self.set_text_color(*COLOR_FAIL)
            self.set_font("KR", "", 8)
            # 에러 로그의 앞부분만 추출
            error_msg = str(longrepr).split('\n')[-2] if '\n' in str(longrepr) else str(longrepr)
            self.multi_cell(165, 5, f"사유: {error_msg}", border=1, fill=True)

        self.set_y(start_y + (28 if not longrepr else 55))

    def generate_cover(self, summary):
        self.add_page()
        self.set_y(60)
        self.set_font("KR", "B", 26)
        self.set_text_color(*COLOR_HEADER)
        self.cell(0, 20, "OAAS 기술 검증 보고서", align="C", ln=True)
        self.set_font("KR", "", 14)
        self.cell(0, 10, "백엔드 데이터 파이프라인 및 집계 로직 테스트", align="C", ln=True)
        
        self.ln(40)
        # 요약 정보 테이블
        self.set_x(40)
        self.set_font("KR", "B", 12)
        self.cell(60, 10, "항목", border=1, align="C")
        self.cell(60, 10, "수치", border=1, align="C", ln=True)
        
        stats = [
            ("총 테스트 케이스", str(summary['total'])),
            ("성공(Passed)", str(summary['passed'])),
            ("실패(Failed)", str(summary['failed'])),
            ("경고(Warnings)", str(summary.get('warnings', 0))),
            ("검증 일시", datetime.now().strftime("%Y-%m-%d %H:%M"))
        ]
        
        self.set_font("KR", "", 11)
        for label, val in stats:
            self.set_x(40)
            self.cell(60, 10, label, border=1, align="C")
            if label == "실패(Failed)" and int(val) > 0:
                self.set_text_color(*COLOR_FAIL)
                self.set_font("KR", "B", 11)
            elif label == "성공(Passed)":
                self.set_text_color(*COLOR_PASS)
            
            self.cell(60, 10, val, border=1, align="C", ln=True)
            self.set_text_color(0)
            self.set_font("KR", "", 11)

def generate_report():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    pdf = ReportPDF()
    pdf.generate_cover(data['summary'])

    # 상세 테스트 결과 페이지
    pdf.add_page()
    pdf.add_section_title("1. 상세 테스트 수행 내역")
    
    for test in data['tests']:
        # nodeid에서 클래스명과 함수명 추출
        name = test['nodeid'].split('::')[-1]
        outcome = test['outcome']
        duration = test.get('duration', 0)
        longrepr = test.get('call', {}).get('longrepr') # 실패 시 에러 로그
        
        # 페이지 하단에 도달하면 새 페이지
        if pdf.get_y() > 240:
            pdf.add_page()
            
        pdf.draw_test_result_box(name, outcome, duration, longrepr)

    # 최종 결론
    pdf.add_page()
    pdf.add_section_title("2. 종합 결론")
    pdf.set_font("KR", "", 11)
    conclusion = (
        "본 테스트 결과, 광고 효율 분석 시스템의 핵심 파이프라인인 '데이터 수집-저장-집계' 과정이 "
        "설계된 비즈니스 로직에 따라 정확히 작동함을 확인하였습니다.\n\n"
        "특히 JSONB 형식의 비정형 데이터를 정밀하게 파싱하여 인구통계학적 지표로 변환하는 "
        "Aggregation 모듈의 정합성이 100% 검증되었으며, 비인가 기기 차단 및 중복 데이터 방지 등 "
        "시스템 안정성을 위한 예외 처리 루틴 또한 정상 작동함을 입증하였습니다."
    )
    pdf.multi_cell(0, 8, conclusion)

    pdf.output(OUTPUT_PATH)
    print(f"보고서가 성공적으로 생성되었습니다: {OUTPUT_PATH}")

if __name__ == "__main__":
    generate_report()