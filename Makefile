.PHONY: install app demo test lint eval replay record sample

install:
	pip install -r requirements.txt ruff

# the Streamlit app (opens on the demo; no key needed)
app:
	streamlit run app/streamlit_app.py

# offline demo: replay the recorded snapshot, write the report in every format to examples/
demo:
	python -m bfa demo --out examples/digital-pathology

test:
	pytest -q

lint:
	ruff check . && ruff format --check .

eval:
	python evaluation/run_eval.py

# repeat the latest saved run and compare the evidence hash
replay:
	python -m bfa replay $$(ls -dt workspace/runs/* | head -1)

# run every connector live and save the responses as a new snapshot (needs network; see .env.example for keys)
record:
	python -m bfa record --brief data/demo/digital_pathology/brief.yaml --yes \
	  --upload data/demo/digital_pathology/uploads/example-diagnostics-lab-survey.pdf:primary:sample

sample:
	python scripts/make_sample_uploads.py
