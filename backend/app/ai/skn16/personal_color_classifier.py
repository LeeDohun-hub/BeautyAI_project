"""
퍼스널 컬러 분류 시스템
계단식 분류 + LAB 거리 계산 방식
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Tuple, List, Dict
import math


@dataclass
class ColorType:
    """퍼스널 컬러 타입 정의"""
    label_id: int
    season: str
    season_eng: str
    subtype: str
    subtype_eng: str
    L: float
    a: float
    b: float
    description: str


class PersonalColorClassifier:
    """퍼스널 컬러 분류기"""
    
    def __init__(self):
        """16가지 퍼스널 컬러 타입 초기화"""
        self.color_types = [
            ColorType(1, "봄 웜톤", "Spring Warm", "봄 라이트", "Spring Light", 78, 15, 20, 
                     "밝고 노란기+맑고 따뜻, 높은 명도"),
            ColorType(2, "봄 웜톤", "Spring Warm", "봄 트루", "Spring True", 76, 16, 22,
                     "높고 따뜻한 오렌지·피치 계열"),
            ColorType(3, "봄 웜톤", "Spring Warm", "봄 브라이트", "Spring Bright", 75, 17, 24,
                     "밝고 선명, 대비감 강, 노랑+오렌지"),
            ColorType(4, "봄 웜톤", "Spring Warm", "봄 클리어", "Spring Clear", 77, 14, 19,
                     "맑고 투명, 원색 포인트"),
            ColorType(5, "여름 쿨톤", "Summer Cool", "여름 라이트", "Summer Light", 74, 13, 14,
                     "연하고 쿨, 소라·로즈 계열"),
            ColorType(6, "여름 쿨톤", "Summer Cool", "여름 소프트", "Summer Soft", 72, 12, 13,
                     "부드럽고 은화, 그레이+핑크톤"),
            ColorType(7, "여름 쿨톤", "Summer Cool", "여름 트루", "Summer True", 73, 14, 13,
                     "퓨어 쿨톤, 네이비·로즈레드"),
            ColorType(8, "여름 쿨톤", "Summer Cool", "여름 뮤트", "Summer Mute", 71, 12, 12,
                     "저명도·저채도, 모브·그레이시톤"),
            ColorType(9, "가을 웜톤", "Autumn Warm", "가을 소프트", "Autumn Soft", 69, 16, 17,
                     "부드러움, 베이지·올리브 계열"),
            ColorType(10, "가을 웜톤", "Autumn Warm", "가을 트루", "Autumn True", 68, 19, 20,
                     "순수 가을, 브라운·오렌지·대지색"),
            ColorType(11, "가을 웜톤", "Autumn Warm", "가을 뮤트", "Autumn Mute", 67, 18, 19,
                     "깊고 차분, 머스타드·딥카키"),
            ColorType(12, "가을 웜톤", "Autumn Warm", "가을 딥", "Autumn Deep", 63, 17, 16,
                     "진하고 어두움, 초콜릿 브라운, 다크"),
            ColorType(13, "겨울 쿨톤", "Winter Cool", "겨울 브라이트", "Winter Bright", 70, 11, 10,
                     "선명·고채도, 블랙&화이트 대비"),
            ColorType(14, "겨울 쿨톤", "Winter Cool", "겨울 트루", "Winter True", 65, 10, 9,
                     "정석 쿨톤, 로얄블루·버건디·실버"),
            ColorType(15, "겨울 쿨톤", "Winter Cool", "겨울 딥", "Winter Deep", 60, 9, 8,
                     "진하고 차가움, 플럼·다크버건디"),
            ColorType(16, "겨울 쿨톤", "Winter Cool", "겨울 클리어", "Winter Clear", 66, 12, 11,
                     "맑고 투명, 아이시·잿빛")
        ]
        
        # Haar Cascade 얼굴 검출기 로드
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        # 계절 분류 임계값 (데이터 분석 기반 최적화)
        # 실제 측정값 분석: L 평균=64.1, b 평균=4.4, b 중앙값=-1.86
        # - 실제 데이터의 55.8%가 쿨톤(-5~0) 영역에 집중
        # - 논문 이론값 대비 L은 4.9 낮고, b는 11.6 낮음
        # 봄/가을만 조정: 웜톤 67, 쿨톤 62 (여름/겨울 유지)
        self.WARM_THRESHOLD = 4.0   # b >= 4 → 웜톤
        self.BRIGHT_THRESHOLD_WARM = 67.0  # 웜톤용: L >= 67 → 봄 (봄/가을 균형)
        self.BRIGHT_THRESHOLD_COOL = 62.0  # 쿨톤용: L >= 62 → 여름 (여름/겨울 유지)
        
        # 가중치 (L, a, b 순서)
        self.weights = np.array([2.0, 1.5, 1.0])
        
        # 조명 보정 (비활성화 - 임계값으로 이미 조정됨)
        self.ENABLE_LIGHTING_CORRECTION = False
        self.LIGHTING_CORRECTION_FACTOR = 8.0  # L값 보정 강도
    
    def detect_face_and_extract_skin(self, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        얼굴 검출 및 피부 영역 추출
        
        Args:
            image: BGR 이미지
            
        Returns:
            (피부_영역_마스크, 얼굴이_그려진_이미지)
        """
        # 그레이스케일 변환 (얼굴 검출용)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # 얼굴 검출
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(100, 100)
        )
        
        if len(faces) == 0:
            raise ValueError("얼굴을 검출할 수 없습니다. 정면 얼굴 사진을 사용해주세요.")
        
        # 가장 큰 얼굴 선택
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        
        # 얼굴 영역 확장 (볼 영역 포함)
        face_roi = image[y:y+h, x:x+w]
        
        # 피부 영역 추출 (YCrCb 색공간 사용)
        ycrcb = cv2.cvtColor(face_roi, cv2.COLOR_BGR2YCrCb)
        
        # 피부색 범위 (밝은 피부 포함하도록 확대)
        lower_skin = np.array([0, 131, 73], dtype=np.uint8)  # Cr, Cb 범위 적당히 확대
        upper_skin = np.array([255, 175, 130], dtype=np.uint8)

        skin_mask = cv2.inRange(ycrcb, lower_skin, upper_skin)

        # 추가: 검은색/매우 어두운 픽셀만 제외 (RGB 기준, 완화)
        gray_check = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        dark_mask = gray_check > 30  # 30 이하만 제외 (진짜 검은색만)
        skin_mask = cv2.bitwise_and(skin_mask, skin_mask, mask=dark_mask.astype(np.uint8) * 255)
        
        # 모폴로지 연산으로 노이즈 제거
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, kernel)
        skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, kernel)
        
        # 볼 중앙 영역만 사용 (더 정확한 피부 톤)
        cheek_mask = np.zeros_like(skin_mask)
        h_roi, w_roi = face_roi.shape[:2]
        
        # 좌측 볼 (코 그림자 피하기 위해 바깥쪽으로 이동)
        left_cheek_x = int(w_roi * 0.15)  # 0.28 → 0.15 (더 바깥쪽)
        left_cheek_y = int(h_roi * 0.45)  # 0.50 → 0.45 (약간 위로)
        left_cheek_w = int(w_roi * 0.15)  # 0.12 → 0.15 (약간 크게)
        left_cheek_h = int(w_roi * 0.15)
        cheek_mask[left_cheek_y:left_cheek_y+left_cheek_h,
                   left_cheek_x:left_cheek_x+left_cheek_w] = 255

        # 우측 볼 (코 그림자 피하기 위해 바깥쪽으로 이동)
        right_cheek_x = int(w_roi * 0.70)  # 0.60 → 0.70 (더 바깥쪽)
        right_cheek_y = int(h_roi * 0.45)  # 0.50 → 0.45 (약간 위로)
        right_cheek_w = int(w_roi * 0.15)  # 0.12 → 0.15 (약간 크게)
        right_cheek_h = int(w_roi * 0.15)
        cheek_mask[right_cheek_y:right_cheek_y+right_cheek_h,
                   right_cheek_x:right_cheek_x+right_cheek_w] = 255
        
        # 피부 마스크와 볼 마스크 결합
        final_mask = cv2.bitwise_and(skin_mask, cheek_mask)
        
        # 시각화용 이미지 생성
        vis_image = image.copy()
        cv2.rectangle(vis_image, (x, y), (x+w, y+h), (0, 255, 0), 2)
        
        # 볼 영역 표시
        cv2.rectangle(vis_image, 
                     (x+left_cheek_x, y+left_cheek_y),
                     (x+left_cheek_x+left_cheek_w, y+left_cheek_y+left_cheek_h),
                     (255, 0, 0), 2)
        cv2.rectangle(vis_image,
                     (x+right_cheek_x, y+right_cheek_y),
                     (x+right_cheek_x+right_cheek_w, y+right_cheek_y+right_cheek_h),
                     (255, 0, 0), 2)
        
        # face_roi에 마스크 적용
        skin_pixels = cv2.bitwise_and(face_roi, face_roi, mask=final_mask)
        
        return skin_pixels, final_mask, vis_image
    
    def extract_lab_values(self, skin_pixels: np.ndarray, mask: np.ndarray) -> Tuple[float, float, float]:
        """
        피부 영역에서 LAB 평균값 추출
        
        Args:
            skin_pixels: 피부 픽셀 이미지
            mask: 피부 마스크
            
        Returns:
            (L, a, b) 평균값
        """
        # LAB 색공간 변환
        lab = cv2.cvtColor(skin_pixels, cv2.COLOR_BGR2LAB)

        # 마스크 영역의 LAB 값만 추출
        masked_lab = lab[mask > 0]

        if len(masked_lab) == 0:
            raise ValueError("유효한 피부 영역을 찾을 수 없습니다.")

        # 추가 필터링: 매우 어두운 픽셀 제외 (L < 30은 검은색에 가까움)
        valid_pixels = masked_lab[masked_lab[:, 0] > 30]

        if len(valid_pixels) == 0:
            raise ValueError("유효한 밝기의 피부 영역을 찾을 수 없습니다. 조명을 확인해주세요.")

        # 밝은 픽셀 우선 선택 (상위 70% 사용)
        # 어두운 그림자 영역 영향 최소화
        percentile_30 = np.percentile(valid_pixels[:, 0], 30)
        bright_pixels = valid_pixels[valid_pixels[:, 0] > percentile_30]

        if len(bright_pixels) < 10:  # 최소 10개 픽셀 필요
            bright_pixels = valid_pixels  # 픽셀이 너무 적으면 전체 사용

        # 평균 계산 (밝은 픽셀만 사용)
        L_mean = np.mean(bright_pixels[:, 0])
        a_mean = np.mean(bright_pixels[:, 1])
        b_mean = np.mean(bright_pixels[:, 2])
        
        # LAB 범위 조정 (OpenCV는 0-255 범위 사용)
        # L: 0-100, a: -128~127, b: -128~127로 변환
        L_mean = L_mean * 100 / 255
        a_mean = a_mean - 128
        b_mean = b_mean - 128
        
        # 조명 보정 (검은 배경/어두운 조명 보상)
        if self.ENABLE_LIGHTING_CORRECTION:
            # L값이 너무 낮으면 보정 (어두운 조명 감지)
            if L_mean < 65:
                correction = self.LIGHTING_CORRECTION_FACTOR
                L_mean = min(L_mean + correction, 85)  # 최대 85까지만
                print(f"[조명 보정] L값 보정: {L_mean - correction:.1f} → {L_mean:.1f}")
        
        return round(L_mean, 2), round(a_mean, 2), round(b_mean, 2)
    
    def classify_season(self, L: float, a: float, b: float) -> str:
        """
        1단계: 4계절 분류 (규칙 기반)
        웜톤과 쿨톤에 각각 다른 밝기 임계값 적용

        Args:
            L, a, b: LAB 값

        Returns:
            계절 ("봄", "여름", "가을", "겨울")
        """
        is_warm = b >= self.WARM_THRESHOLD

        # 웜톤과 쿨톤에 다른 임계값 적용
        if is_warm:
            # 웜톤: 봄/가을 구분
            is_bright = L >= self.BRIGHT_THRESHOLD_WARM
        else:
            # 쿨톤: 여름/겨울 구분
            is_bright = L >= self.BRIGHT_THRESHOLD_COOL

        if is_warm and is_bright:
            return "봄"
        elif is_warm and not is_bright:
            return "가을"
        elif not is_warm and is_bright:
            return "여름"
        else:
            return "겨울"

    def classify_subtype_relative(self, L: float, a: float, b: float, season: str) -> str:
        """
        2단계: 상대적 위치 기반 세부 타입 분류
        각 계절 내에서 L과 b 값의 상대적 위치로 4가지 세부 타입 구분

        Args:
            L, a, b: LAB 값
            season: 계절 ("봄", "여름", "가을", "겨울")

        Returns:
            세부 타입명
        """
        # 각 계절별 실제 데이터 중앙값 기반 임계값
        # (테스트 데이터 52개 샘플 분석 결과)
        season_ranges = {
            "봄": {
                "L_mid": 72.6,  # 실제 중앙값 (68.92~76.10 범위)
                "b_mid": 17.8,   # 실제 중앙값 (12.03~20.20 범위)
                "types": {
                    (True, True): "봄 브라이트",   # 밝고, 강한 웜톤
                    (True, False): "봄 라이트",     # 밝고, 약한 웜톤
                    (False, True): "봄 트루",       # 어둡고, 강한 웜톤
                    (False, False): "봄 클리어"     # 어둡고, 약한 웜톤
                }
            },
            "여름": {
                "L_mid": 65.0,  # 실제 중앙값 (62.09~69.16 범위)
                "b_mid": -2.4,   # 실제 중앙값 (-3.00~0.61 범위)
                "types": {
                    (True, True): "여름 라이트",    # 밝고, 강한 쿨톤
                    (True, False): "여름 소프트",    # 밝고, 약한 쿨톤
                    (False, True): "여름 트루",      # 어둡고, 강한 쿨톤
                    (False, False): "여름 뮤트"      # 어둡고, 약한 쿨톤
                }
            },
            "가을": {
                "L_mid": 60.5,  # 조정: 가을_딥 균형 (59.4 → 60.5)
                "b_mid": 9.5,    # 조정: 가을_딥 균형 (8.8 → 9.5)
                "types": {
                    (True, True): "가을 소프트",    # 밝고, 강한 웜톤
                    (True, False): "가을 뮤트",      # 밝고, 약한 웜톤
                    (False, True): "가을 트루",      # 어둡고, 강한 웜톤
                    (False, False): "가을 딥"        # 어둡고, 약한 웜톤
                }
            },
            "겨울": {
                "L_mid": 59.4,  # 실제 중앙값 (53.27~61.68 범위)
                "b_mid": -2.6,   # 실제 중앙값 (-3.00~1.64 범위)
                "types": {
                    (True, True): "겨울 브라이트",  # 밝고, 강한 쿨톤
                    (True, False): "겨울 클리어",    # 밝고, 약한 쿨톤
                    (False, True): "겨울 트루",      # 어둡고, 강한 쿨톤
                    (False, False): "겨울 딥"        # 어둡고, 약한 쿨톤
                }
            }
        }

        if season not in season_ranges:
            # 폴백: 거리 기반으로 돌아감
            return None

        range_info = season_ranges[season]

        # 상대적 위치 판단
        is_bright = L >= range_info["L_mid"]

        # 웜톤 계절(봄/가을)은 b가 높을수록 강함
        # 쿨톤 계절(여름/겨울)은 b가 낮을수록 강함
        if season in ["봄", "가을"]:
            is_strong = b >= range_info["b_mid"]
        else:  # 여름, 겨울
            is_strong = b <= range_info["b_mid"]

        return range_info["types"][(is_bright, is_strong)]
    
    def calculate_weighted_distance(self, 
                                   measured: Tuple[float, float, float],
                                   reference: Tuple[float, float, float]) -> float:
        """
        가중치를 적용한 유클리드 거리 계산
        
        Args:
            measured: 측정된 LAB 값
            reference: 기준 LAB 값
            
        Returns:
            가중치 적용 거리
        """
        diff = np.array(measured) - np.array(reference)
        weighted_diff = diff * self.weights
        distance = np.sqrt(np.sum(weighted_diff ** 2))
        return distance
    
    def calculate_probabilities(self, distances: Dict[str, float]) -> Dict[str, float]:
        """
        거리를 확률로 변환 (개선된 버전)
        
        Args:
            distances: {타입명: 거리} 딕셔너리
            
        Returns:
            {타입명: 확률} 딕셔너리
        """
        # 방법 1: 소프트맥스 with 온도 파라미터
        # 온도가 낮을수록 최고값에 집중, 높을수록 고르게 분산
        temperature = 1.5  # 조정: 2.0 → 1.5 (확신도 증가)
        
        # 거리를 음수로 만들어서 소프트맥스 적용 (거리 짧을수록 높은 확률)
        neg_distances = {k: -v / temperature for k, v in distances.items()}
        
        # exp 계산
        max_val = max(neg_distances.values())  # 오버플로우 방지
        exp_scores = {k: np.exp(v - max_val) for k, v in neg_distances.items()}
        
        # 정규화
        total = sum(exp_scores.values())
        probabilities = {k: (v / total) * 100 for k, v in exp_scores.items()}
        
        return probabilities
    
    def classify(self, image: np.ndarray) -> Dict:
        """
        퍼스널 컬러 분류 (전체 파이프라인)

        Args:
            image: BGR 이미지

        Returns:
            분류 결과 딕셔너리
        """
        # 1. 얼굴 검출 및 피부 영역 추출
        # Support subclasses that may return either (skin, mask, vis) or
        # (skin, masks_tuple, vis, eyes_detected). Be lenient for backward
        # compatibility.
        dfes = self.detect_face_and_extract_skin(image)
        if isinstance(dfes, tuple) and len(dfes) == 4:
            skin_pixels, skin_mask, vis_image, _eyes = dfes
        else:
            skin_pixels, skin_mask, vis_image = dfes

        # 2. LAB 값 추출
        L, a, b = self.extract_lab_values(skin_pixels, skin_mask)

        # 3. 1단계: 4계절 분류
        season = self.classify_season(L, a, b)

        # 디버그 출력
        print(f"\n[디버그] 측정된 LAB 값: L={L:.1f}, a={a:.1f}, b={b:.1f}")
        print(f"[디버그] 4계절 분류 결과: {season}")

        # 4. 2단계: 상대적 위치 기반 세부 타입 분류
        relative_subtype = self.classify_subtype_relative(L, a, b, season)

        if relative_subtype:
            # 상대적 방식 성공
            print(f"[디버그] 상대적 위치 기반 분류: {relative_subtype}")
            best_type = next(ct for ct in self.color_types if ct.subtype == relative_subtype)

            # 해당 계절의 모든 타입과 거리 계산 (참고용)
            season_types = [ct for ct in self.color_types if season in ct.season]
            distances = {}
            for color_type in season_types:
                dist = self.calculate_weighted_distance(
                    (L, a, b),
                    (color_type.L, color_type.a, color_type.b)
                )
                distances[color_type.subtype] = dist
                print(f"[디버그] {color_type.subtype}: 거리={dist:.2f} (기준 L={color_type.L}, a={color_type.a}, b={color_type.b})")

            # 확률은 거리 기반으로 계산
            probabilities = self.calculate_probabilities(distances)
            sorted_results = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)
            top3 = sorted_results[:3]

            # 최종 타입의 확률 (상대적 위치 기반 분류 결과 사용)
            confidence = probabilities[relative_subtype]
        else:
            # 폴백: 거리 기반 분류
            print(f"[디버그] 폴백: 거리 기반 분류 사용")
            season_types = [ct for ct in self.color_types if season in ct.season]

            distances = {}
            for color_type in season_types:
                dist = self.calculate_weighted_distance(
                    (L, a, b),
                    (color_type.L, color_type.a, color_type.b)
                )
                distances[color_type.subtype] = dist
                print(f"[디버그] {color_type.subtype}: 거리={dist:.2f} (기준 L={color_type.L}, a={color_type.a}, b={color_type.b})")

            # 확률 계산
            probabilities = self.calculate_probabilities(distances)
            sorted_results = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)
            top3 = sorted_results[:3]

            best_type = next(ct for ct in self.color_types if ct.subtype == top3[0][0])
            confidence = top3[0][1]

        # 9. 확신도 판단 (상대적 위치 기반일 때도 이미 confidence 설정됨)
        if confidence >= 60:
            status = "confident"
            message = f"당신의 퍼스널컬러는 **{best_type.subtype}**입니다!"
        elif confidence >= 40:
            status = "uncertain"
            second_type = next(ct for ct in self.color_types if ct.subtype == top3[1][0])
            message = f"**{best_type.subtype}** 또는 **{second_type.subtype}**일 가능성이 높습니다."
        else:
            status = "require_expert"
            message = "AI 분석으로는 정확한 판단이 어렵습니다. 전문가 상담을 권장합니다."

        return {
            'status': status,
            'message': message,
            'lab_values': {'L': L, 'a': a, 'b': b},
            'season': season,
            'best_type': {
                'name': best_type.subtype,
                'name_eng': best_type.subtype_eng,
                'season': best_type.season,
                'description': best_type.description,
            },
            'top3': [
                {
                    'name': t[0],
                } for t in top3
            ],
            'visualization': vis_image
        }


def format_result(result: Dict) -> str:
    """결과를 읽기 좋게 포맷팅"""
    
    output = f"""
# 🎨 퍼스널 컬러 분석 결과

## {result['message']}

---

### 📊 측정된 LAB 값 (볼 중앙 영역 기준)
- **L (명도)**: {result['lab_values']['L']:.1f} / 100 (밝기, 높을수록 밝음)
- **a (빨강-녹색)**: {result['lab_values']['a']:.1f} (양수: 빨강, 음수: 녹색)
- **b (노랑-파랑)**: {result['lab_values']['b']:.1f} (양수: 노랑=웜톤, 음수: 파랑=쿨톤)

### 🌸 1단계: 4계절 분류 근거

**{result['season']}** 타입으로 분류되었습니다.

**분류 기준:**
- **b값 (웜/쿨 판단)**: {result['lab_values']['b']:.1f} {'≥' if result['lab_values']['b'] >= 15 else '<'} 15.0 → **{'웜톤 (봄/가을)' if result['lab_values']['b'] >= 15 else '쿨톤 (여름/겨울)'}**
- **L값 (밝기 판단)**: {result['lab_values']['L']:.1f} {'≥' if result['lab_values']['L'] >= 70 else '<'} 70.0 → **{'밝음 (봄/여름)' if result['lab_values']['L'] >= 70 else '어두움 (가을/겨울)'}**

---

### 🏆 2단계: 세부 타입 분류 결과

**{result['best_type']['name']}** ({result['best_type']['probability']:.1f}%)

- **계절**: {result['best_type']['season']}
- **특징**: {result['best_type']['description']}

**선택 근거:**
{result['season']} 계절 내 4가지 타입 중에서 측정된 LAB 값과의 **거리가 가장 가까운** 타입입니다.

---

### 📈 상위 3개 가능성 (거리 기반)

"""

    for i, item in enumerate(result['top3'], 1):
        medal = ['🥇', '🥈', '🥉'][i-1]
        output += f"{medal} **{item['name']}**: {item['probability']:.1f}% (LAB 거리: {item['distance']:.2f})\n"
    
    output += "\n---\n\n"
    
    if result['status'] == 'confident':
        output += "### ✅ 신뢰도: 높음\n"
        output += "이 결과는 높은 확신도를 가지고 있습니다."
    elif result['status'] == 'uncertain':
        output += "### ⚠️ 신뢰도: 중간\n"
        output += "더 정확한 진단을 위해:\n"
        output += "- 자연광에서 촬영한 사진 사용\n"
        output += "- 다른 각도의 사진 추가 업로드\n"
        output += "- 메이크업 없는 상태 권장"
    else:
        output += "### ❌ 신뢰도: 낮음\n"
        output += "전문 컬러리스트 상담을 강력히 권장합니다."
    
    return output