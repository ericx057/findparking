from pydantic import BaseModel


class ParkingLot(BaseModel):
    lot_id: str
    name: str
    latitude: float
    longitude: float
    capacity: int
    current_occupancy: int = 0
    last_updated: str | None = None
    camera_source_url: str | None = None
    tripwire_config: str | None = None


class VehicleEventCreate(BaseModel):
    direction: str
    confidence: float = 1.0


class VehicleEvent(BaseModel):
    event_id: int
    lot_id: str
    direction: str
    timestamp: str
    confidence: float


class OccupancySnapshot(BaseModel):
    snapshot_id: int
    lot_id: str
    occupancy: int
    vacancy_ratio: float
    probability_score: float
    timestamp: str


class LotProbability(BaseModel):
    lot_id: str
    name: str
    latitude: float
    longitude: float
    capacity: int
    current_occupancy: int
    vacancy_ratio: float
    probability_score: float
    availability: str
    trend: str | None = None
    freshness_seconds: float | None = None
    confidence_range: str | None = None
    last_updated: str | None = None
