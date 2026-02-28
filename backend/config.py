from pydantic_settings import BaseSettings


class ParkingFinderSettings(BaseSettings):
    db_path: str = "findparking.db"
    city: str = "waterloo"
    purge_hour: int = 3
    poll_interval_seconds: int = 30
    log_level: str = "INFO"
    ticketmaster_api_key: str = ""

    model_config = {"env_prefix": "PARKING_"}
