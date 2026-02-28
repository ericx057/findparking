import json
from dataclasses import dataclass, field


@dataclass
class TripwireConfig:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class CameraConfig:
    lot_id: str
    camera_url: str
    poll_interval_seconds: float = 10.0
    tripwires: list[TripwireConfig] = field(default_factory=list)


def load_cameras_config(path: str) -> list[CameraConfig]:
    with open(path) as f:
        data = json.load(f)

    cameras = []
    for cam in data.get("cameras", []):
        tripwires = [
            TripwireConfig(**tw) for tw in cam.get("tripwires", [])
        ]
        cameras.append(CameraConfig(
            lot_id=cam["lot_id"],
            camera_url=cam["camera_url"],
            poll_interval_seconds=cam.get("poll_interval_seconds", 10.0),
            tripwires=tripwires,
        ))
    return cameras
