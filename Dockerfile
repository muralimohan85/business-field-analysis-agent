# Runs the Streamlit app (no API key needed; paste one in the sidebar for the Claude engine).
# Works on Hugging Face Spaces (Docker SDK), Render, Fly.io, or locally:
#   docker build -t bfa-agent . && docker run -p 7860:7860 bfa-agent
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd -m appuser && chown -R appuser /app
USER appuser
ENV BFA_WORKSPACE=/tmp/bfa-workspace MPLCONFIGDIR=/tmp/mpl

EXPOSE 7860
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=7860", "--server.address=0.0.0.0"]
