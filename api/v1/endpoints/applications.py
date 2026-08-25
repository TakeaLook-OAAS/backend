import re
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.database import get_db
from core.deps import get_current_user
from core.geocoding import geocode_address, GeocodingError
from database.enums import CampaignStatus, DeviceStatus
import database.models as models
import database.schemas as schemas

router = APIRouter()

VALID_CATEGORIES = {"fnb", "fashion", "beauty", "it", "fin", "edu", "med", "pub"}
VALID_PLACEMENTS = {"indoor", "outdoor"}
VALID_GENDERS    = {"all", "m", "f"}
VALID_AGES       = {"10-19", "20-29", "30-39", "40-49", "50-59", "60+", "all"}
TIME_RE          = re.compile(r"^\d{2}:\d{2}$")


def _generate_device_name(db: Session) -> str:
    """
    새 기기 이름을 'device-001' 형식으로 생성한다.
    현재 등록된 기기 수 + 1을 기준으로 순번을 매기고, 혹시 몰라 충돌 시 재시도한다.
    (동시에 두 신청이 들어와도 unique 제약 위반이면 뒤에 랜덤 suffix를 붙여 재시도)
    """
    count = db.query(models.Device).count()
    candidate = f"device-{count + 1:03d}"
    if not db.query(models.Device).filter(models.Device.name == candidate).first():
        return candidate
    # 드물게 경합이 있었던 경우 — 랜덤 접미사로 충돌 회피
    return f"device-{count + 1:03d}-{secrets.token_hex(2)}"


@router.post("/", response_model=schemas.ApplicationResponse, status_code=201)
def submit_application(
    body: schemas.ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not body.brand.strip():
        raise HTTPException(400, "브랜드명을 입력해 주세요.")
    if not body.company.strip():
        raise HTTPException(400, "회사명을 입력해 주세요.")
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(400, f"유효하지 않은 카테고리입니다: {body.category}")
    if body.end_date < body.start_date:
        raise HTTPException(400, "종료일은 시작일 이후여야 합니다.")
    if not TIME_RE.match(body.start_time) or not TIME_RE.match(body.end_time):
        raise HTTPException(400, "시간 형식이 올바르지 않습니다. HH:MM 형식으로 입력해 주세요.")
    if body.start_time >= body.end_time:
        raise HTTPException(400, "종료 시간은 시작 시간 이후여야 합니다.")
    if body.placement not in VALID_PLACEMENTS:
        raise HTTPException(400, f"유효하지 않은 광고 위치입니다: {body.placement}")
    if not body.addresses or not any(a.addr.strip() for a in body.addresses):
        raise HTTPException(400, "광고 주소를 하나 이상 입력해 주세요.")

    # 주소마다: 이미 그 주소로 신청된 적 있는 기기가 있으면 재사용,
    # 처음 신청되는 주소면 지오코딩해서 새 기기를 생성한다.
    matched_devices: dict[str, models.Device] = {}
    for a in body.addresses:
        addr = a.addr.strip()
        if addr in matched_devices:
            continue  # 같은 신청서 안에 같은 주소가 중복 입력된 경우

        device = db.query(models.Device).filter(models.Device.address == addr).first()
        if device is None:
            try:
                latitude, longitude = geocode_address(addr)
            except GeocodingError as e:
                raise HTTPException(400, f"'{addr}' 주소의 좌표를 찾을 수 없습니다: {e}")

            # 동시에 두 요청이 같은 이름 후보를 뽑을 수 있으므로, 충돌 시 짧게 재시도한다.
            # SAVEPOINT(begin_nested)로 감싸서, 실패해도 이번 기기 시도만 되돌아가고
            # 같은 신청서에서 앞서 처리된 다른 주소의 기기는 영향받지 않는다.
            MAX_RETRIES = 3
            for attempt in range(MAX_RETRIES):
                try:
                    with db.begin_nested():
                        device = models.Device(
                            name=_generate_device_name(db),
                            address=addr,
                            latitude=latitude,
                            longitude=longitude,
                            timezone="Asia/Seoul",
                            status=DeviceStatus.MAINTENANCE,  # 아직 실제 설치 전 — 설치팀이 확인 후 ENABLE로 전환
                        )
                        db.add(device)
                        db.flush()  # 이후 device.id를 바로 참조하기 위해 flush (커밋은 아직 안 함)
                    break
                except IntegrityError:
                    if attempt == MAX_RETRIES - 1:
                        raise HTTPException(
                            500, "기기 등록 중 이름 충돌이 반복되어 실패했습니다. 다시 시도해 주세요."
                        )
                    # 다음 루프에서 count()가 갱신된 값을 다시 읽어 새 후보를 만듦

        matched_devices[addr] = device

    if body.age not in VALID_AGES:
        raise HTTPException(400, "타겟 연령층을 선택해 주세요.")
    if body.gender not in VALID_GENDERS:
        raise HTTPException(400, "유효하지 않은 성별 값입니다.")
    if not body.name.strip():
        raise HTTPException(400, "담당자 이름을 입력해 주세요.")
    if not body.phone.strip():
        raise HTTPException(400, "연락처를 입력해 주세요.")
    if not body.email.strip() or "@" not in body.email:
        raise HTTPException(400, "유효한 이메일을 입력해 주세요.")
    if not body.slot_configs or not any(
        sc.adLength and sc.adLength > 0 for sc in body.slot_configs
    ):
        raise HTTPException(400, "슬롯 구성을 입력해 주세요.")

    gender_map = {"m": "male", "f": "female", "all": None}
    target_gender = gender_map[body.gender]
    target_age_group = None if body.age == "all" else body.age

    campaign = models.Campaign(
        user_id          = current_user.id,
        name             = body.brand.strip(),
        start_date       = body.start_date,
        end_date         = body.end_date,
        status           = CampaignStatus.DRAFT,
        target_age_group = target_age_group,
        target_gender    = target_gender,
        brand            = body.brand.strip(),
        company          = body.company.strip(),
        category         = body.category,
        placement        = body.placement,
        start_time       = body.start_time,
        end_time         = body.end_time,
        slot_configs     = [sc.model_dump() for sc in body.slot_configs],
        addresses        = [
            {"addr": a.addr, "label": a.label, "device_id": str(matched_devices[a.addr.strip()].id)}
            for a in body.addresses
        ],
        contact_name     = body.name.strip(),
        contact_phone    = body.phone.strip(),
        contact_email    = body.email.strip(),
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign