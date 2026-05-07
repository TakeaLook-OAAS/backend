import enum

# 기기 상태 : Enable(활성화), Disable(비활성화), Maintenance(유지보수중)
class DeviceStatus(str, enum.Enum):
    ENABLE = "ENABLE"
    DISABLE = "DISABLE"
    MAINTENANCE = "MAINTENANCE"

# 광고 상태 : Draft(임시), Running(광고 중), Paused(정지 상태), Ended(광고 기간이 지남)
class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ENDED = "ENDED"

# 계정 권한 : Admin(관리자), User(일반 사용자)
class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"