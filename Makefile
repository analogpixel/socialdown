
run:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

setup:
	pip install -r requiremnts.txt
