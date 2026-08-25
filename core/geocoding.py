"""
네이버 클라우드 플랫폼 API를 이용한 지오코딩 모듈
- 주소 문자열 -> (위도, 경도) 좌표 변환
- NCP_MAP_API_KEY_ID, NCP_MAP_API_KEY 환경변수 필요
"""
import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

NCP_GEOCODE_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"

NCP_MAP_API_KEY_ID = os.getenv("NCP_MAP_API_KEY_ID")
NCP_MAP_API_KEY = os.getenv("NCP_MAP_API_KEY")


class GeocodingError(Exception):
    """지오코딩 실패 시 발생 (주소를 못 찾음, API 키 오류, 네트워크 오류 등)"""
    pass


def geocode_address(address: str) -> tuple[float, float]:
    """주소 문자열을 (latitude, longitude)로 변환합니다. 실패 시 GeocodingError."""
    if not NCP_MAP_API_KEY_ID or not NCP_MAP_API_KEY:
        raise GeocodingError("NCP_MAP_API_KEY_ID / NCP_MAP_API_KEY 환경변수가 설정되지 않았습니다.")

    headers = {
        "X-NCP-APIGW-API-KEY-ID": NCP_MAP_API_KEY_ID,
        "X-NCP-APIGW-API-KEY": NCP_MAP_API_KEY,
        "Accept": "application/json",
    }
    params = {"query": address}

    try:
        response = httpx.get(NCP_GEOCODE_URL, headers=headers, params=params, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"[Geocoding] NCP API 오류 응답: {e.response.status_code} | address={address}")
        raise GeocodingError(f"네이버 지오코딩 API 오류: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"[Geocoding] 네트워크 오류: {e} | address={address}")
        raise GeocodingError(f"네이버 지오코딩 API 요청 실패: {e}")

    data = response.json()

    if data.get("status") != "OK" or not data.get("addresses"):
        logger.warning(f"[Geocoding] 주소 검색 결과 없음: address={address} | response={data}")
        raise GeocodingError(f"'{address}'에 대한 좌표를 찾을 수 없습니다.")

    best = data["addresses"][0]
    return float(best["y"]), float(best["x"])   # (latitude, longitude)


def try_geocode_address(address: str) -> Optional[tuple[float, float]]:
    """
    geocode_address()의 예외 안 던지는 버전.
    캠페인 신청 자체를 막지 않기 위해, 실패해도 None만 반환하고 로그만 남김.
    (신청 폼 제출은 주소 정확도와 무관하게 항상 성공해야 하므로)
    """
    try:
        return geocode_address(address)
    except GeocodingError as e:
        logger.warning(f"[Geocoding] 지오코딩 실패, 좌표 없이 진행: {e}")
        return None