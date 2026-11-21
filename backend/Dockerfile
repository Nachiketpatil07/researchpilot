# ResearchPilot API: CPU-only image (no torch; models run on ONNX Runtime).
# Built by Hugging Face Spaces (port 7860), also works locally:
#   docker build -t researchpilot-api backend && docker run -p 7860:7860 -e GROQ_API_KEY=... researchpilot-api
FROM python:3.12-slim

# Spaces run containers as UID 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    DATA_DIR=/home/user/data \
    DEMO_MODE=true \
    CORS_ORIGIN_REGEX='https://.*\.vercel\.app'
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user app ./app
COPY --chown=user eval/results/latest.json ./eval/results/latest.json

# Bake models and demo papers into the image so a cold start only has to index.
RUN python -m app.cli warm-models && python -m app.cli samples

EXPOSE 7860
# Index the papers on first start (needs GROQ_API_KEY for document summaries), then serve.
CMD ["sh", "-c", "python -m app.cli bootstrap && exec uvicorn app.api:app --host 0.0.0.0 --port 7860"]
