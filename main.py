"""MAC 기반 Mini NPU 시뮬레이터."""

import json
import re
import sys
import time
from pathlib import Path

EPSILON = 1e-9
SIZES = (3, 5, 13, 25)
PATTERN_KEY = re.compile(r"size_(\d+)_(\d+)") # e.g) size_13_7


# 입력값이 숫자로 이루어진 정사각 행렬인지 확인한다.
def validate_matrix(value):
    #EAFP(Easy to Ask Forgiveness than Permission) pattern
    if not isinstance(value, list) or not value:
        raise ValueError("행렬은 비어 있지 않은 2차원 리스트여야 합니다.")
    size = len(value)
    if any(not isinstance(row, list) or len(row) != size for row in value):
        raise ValueError("NxN 정사각 행렬이어야 합니다.")
    try:
        return [[float(item) for item in row] for row in value]
    except (TypeError, ValueError) as error:
        raise ValueError("행렬에는 숫자만 포함되어야 합니다.") from error


# 두 행렬의 같은 위치 값을 곱하고 모두 더한다.
def mac(pattern, filter_):
    """두 NxN 행렬의 같은 위치를 곱해 모두 더한다."""
    left, right = validate_matrix(pattern), validate_matrix(filter_)
    if len(left) != len(right):
        raise ValueError("두 행렬의 크기가 다릅니다.")
    score = 0.0
    for row in range(len(left)):
        for column in range(len(left)):
            score += left[row][column] * right[row][column]
    return score


# 두 점수를 비교해 Cross, X, UNDECIDED 중 하나를 반환한다.
def decide(cross_score, x_score):
    if abs(cross_score - x_score) < EPSILON:
        return "UNDECIDED"
    return "Cross" if cross_score > x_score else "X"


# JSON의 다양한 라벨 표기를 표준 라벨로 통일한다.
def normalize_label(label):
    value = str(label).strip().lower()
    if value in {"+", "cross"}:
        return "Cross"
    if value == "x":
        return "X"
    raise ValueError(f"지원하지 않는 라벨입니다: {label}")


# 사용자의 입력을 안전하게 받아 중단 상황을 처리한다.
def safe_input(prompt=""):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt) as error:
        print("\n입력이 중단되었습니다. 프로그램을 종료합니다.")
        raise SystemExit(0) from error


# 사용자에게 행렬을 입력받고 형식을 검증한다.
def read_matrix(name, size=3):
    while True:
        print(f"\n{name} ({size}줄 입력, 공백 구분)")
        lines = [safe_input() for _ in range(size)]
        try:
            rows = [line.split() for line in lines]
            if any(len(row) != size for row in rows):
                raise ValueError(f"각 줄에 {size}개의 숫자를 공백으로 구분해 입력하세요.")
            return validate_matrix(rows)
        except ValueError as error:
            print(f"입력 형식 오류: {error}\n다시 입력해주세요.")


# 입력한 두 필터를 보여주고 진행 여부를 확인한다.
def confirm_filters(filter_a, filter_b):
    # 행렬을 읽기 쉬운 형태로 출력한다.
    def show(matrix):
        for row in matrix:
            # 정수처럼 표현할 수 있는 값은 .0을 제거
            print(" ".join(str(int(value)) if value.is_integer() else str(value) for value in row))

    print("\n입력한 필터를 확인합니다.\n필터 A")
    show(filter_a)
    print("\n필터 B")
    show(filter_b)
    while True:
        answer = safe_input("\n이 필터로 진행할까요? (y/n): ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("y 또는 n만 입력해주세요.")


# MAC 연산을 반복해 평균 실행 시간을 측정한다.
def elapsed_ms(pattern, filter_, repeat=10):
    start = time.perf_counter()
    for _ in range(repeat):
        mac(pattern, filter_)
    return (time.perf_counter() - start) * 1000 / repeat


# JSON 파일을 읽고 최상위 구조를 검증한다.
def load_data(path):
    try:
        with Path(path).open(encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise ValueError(f"파일을 찾을 수 없습니다: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON 로드 실패: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("JSON 최상위 구조는 객체(dict)여야 합니다.")
    return data


# 패턴 키에서 행렬 크기 N을 추출한다.
def pattern_size(key):
    match = PATTERN_KEY.fullmatch(key)
    if not match:
        raise ValueError(f"패턴 키 형식 오류: {key}")
    return int(match.group(1))


# 지정한 크기의 Cross 필터와 X 필터를 찾아 검증한다.
def get_filters(filters, size):
    # 크기 이름 만들기
    size_key = f"size_{size}"
    # 해당 크기의 필터 묶음 가져오기
    item = filters.get(size_key)
    # 필터 묶음이 딕셔너리인지 확인
    if not isinstance(item, dict):
        raise ValueError(f"필터 누락 또는 구조 오류: {size_key}")
    try:
        # Cross와 X 필터 가져오기
        cross = item.get("Cross", item.get("cross"))
        x_filter = item.get("X", item.get("x"))
        # 실제 행렬 검증
        cross, x_filter = validate_matrix(cross), validate_matrix(x_filter)
    except (TypeError, ValueError) as error:
        raise ValueError(f"필터 구조 오류: {size_key}") from error
    # 행렬 크기 확인
    if len(cross) != size or len(x_filter) != size:
        raise ValueError(f"필터 크기 불일치: {size_key}")
    return cross, x_filter


# 크기별 평균 시간과 MAC 연산 횟수를 출력한다.
def print_benchmark(results, filters):
    print("\n=== 성능 분석 (평균/10회) ===\n크기\t평균 시간(ms)\t연산 횟수")
    for size in SIZES:
        times = [item["time"] for item in results if item["size"] == size and item["time"] is not None]
        if not times:
            try:
                cross, _ = get_filters(filters, size)
                times = [elapsed_ms(cross, cross)]
            except ValueError:
                pass
        average = f"{sum(times) / len(times):.6f}" if times else "-"
        print(f"{size}×{size}\t{average}\t{size * size}")


# 전체 테스트 결과와 실패 케이스를 요약한다.
def print_summary(results):
    passed = sum(item["passed"] for item in results)
    print(f"\n=== 결과 요약 ===\n총 테스트: {len(results)}개\n통과: {passed}개\n실패: {len(results) - passed}개")
    failures = [item for item in results if not item["passed"]]
    if failures:
        print("실패 케이스:")
        for item in failures:
            print(f"- {item['key']}: {item['reason']}")


# data.json의 모든 패턴을 판정하고 결과를 출력한다.
def analyze_json(path):
    try:
        # JSON을 읽고 filters와 patterns가 딕셔너리인지 확인한다.
        data = load_data(path)
        filters, patterns = data["filters"], data["patterns"]
        if not isinstance(filters, dict) or not isinstance(patterns, dict):
            raise ValueError("filters와 patterns는 객체(dict)여야 합니다.")
    except (KeyError, ValueError) as error:
        print(f"FAIL: {error}")
        return

    print("\n=== 필터 로드 ===")
    for size in (5, 13, 25):
        try:
            get_filters(filters, size)
            print(f"✓ size_{size} 필터 로드 완료 (Cross, X)")
        except ValueError as error:
            print(f"FAIL: {error}")

    results = []
    print("\n=== 패턴 분석 (라벨 정규화 적용) ===")
    for key, item in patterns.items():
        # 오류가 발생해도 전체 분석을 계속할 수 있도록 케이스별 결과를 미리 만든다.
        result = {"key": key, "size": None, "time": None, "passed": False, "reason": ""}
        try:
            if not isinstance(item, dict) or "input" not in item or "expected" not in item:
                raise ValueError("패턴에는 input과 expected가 필요합니다.")
            # 패턴 키의 크기와 실제 입력 행렬의 크기를 검증한다.
            size = pattern_size(key)
            pattern = validate_matrix(item["input"])
            if len(pattern) != size:
                raise ValueError("패턴 크기와 키의 size 값이 일치하지 않습니다.")
            # 같은 크기의 Cross/X 필터로 두 점수를 계산하고 라벨을 통일한다.
            cross, x_filter = get_filters(filters, size)
            scores = mac(pattern, cross), mac(pattern, x_filter)
            predicted, expected = decide(*scores), normalize_label(item["expected"])
            # 판정 결과와 성능 측정값을 현재 케이스의 결과에 저장한다.
            result.update(size=size, time=elapsed_ms(pattern, cross), passed=predicted == expected)
            # 실패한 경우에는 동점인지 단순 오판인지 구분해 원인을 기록한다.
            result["reason"] = "" if result["passed"] else ("동점(UNDECIDED) 처리 규칙에 따라 FAIL" if predicted == "UNDECIDED" else f"예측값({predicted})과 expected({expected}) 불일치")
            print(f"\n--- {key} ---\nCross 점수: {scores[0]}\nX 점수: {scores[1]}")
            print(f"판정: {predicted} | expected: {expected} | {'PASS' if result['passed'] else 'FAIL'}")
        except (TypeError, ValueError, AttributeError) as error:
            # 한 케이스의 오류를 기록하고 다음 패턴 분석으로 넘어간다.
            result["reason"] = str(error)
            print(f"\n--- {key} ---\nFAIL: {error}")
        # 정상 케이스와 오류 케이스 모두 결과 목록에 포함한다.
        results.append(result)
    print_benchmark(results, filters)
    print_summary(results)


# 사용자 입력 행렬의 MAC 점수와 판정 결과를 출력한다.
def user_mode():
    while True:
        filter_a, filter_b = read_matrix("필터 A"), read_matrix("필터 B")
        if confirm_filters(filter_a, filter_b):
            break
    pattern = read_matrix("패턴")
    score_a, score_b = mac(pattern, filter_a), mac(pattern, filter_b)
    print(f"\n=== MAC 결과 ===\nA 점수: {score_a}\nB 점수: {score_b}")
    print(f"연산 시간(평균/10회): {elapsed_ms(pattern, filter_a):.6f} ms")
    result = decide(score_a, score_b)
    result = {"Cross": "A", "X": "B", "UNDECIDED": "판정 불가"}[result]
    print(f"판정: {result}")


# 메뉴를 출력하고 선택한 모드를 실행한다.
def main():
    default_path = "data/data.json"
    for path in ("data/data.json", "data.json"):
        if Path(path).exists():
            default_path = path
            break

    path = sys.argv[1] if len(sys.argv) > 1 else default_path
    print("=== Mini NPU Simulator ===\n\n[모드 선택]\n\n1. 사용자 입력 (3x3)\n2. data.json 분석")
    choice = safe_input("선택: ").strip()
    if choice == "1":
        user_mode()
    elif choice == "2":
        analyze_json(path)
    else:
        print("지원하지 않는 메뉴입니다. 1 또는 2를 선택해주세요.")


if __name__ == "__main__":
    main()
