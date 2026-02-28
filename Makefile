.PHONY: install install-cv test run-backend run-mock run-pipeline lint seed discover-cameras

install:
	pip install -r requirements.txt

install-cv:
	pip install -r requirements-cv.txt

test:
	pytest tests/ -v

run-backend:
	uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

run-mock:
	python -m cv_pipeline.mock_pipeline --city $(or $(CITY),waterloo)

run-pipeline:
	python run_pipeline.py

lint:
	python -m py_compile backend/*.py cv_pipeline/*.py

seed:
	python seed_lots.py $(if $(CITY),--city $(CITY),)

discover-cameras:
	python -m cv_pipeline.camera_discovery --city $(or $(CITY),waterloo)
