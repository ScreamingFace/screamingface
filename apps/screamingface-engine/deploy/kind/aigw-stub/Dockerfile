# aigw-stub — a stand-in for aigateway inside the kind environment (uniform executor
# test-plan §5). Build context is THIS directory (unlike the engine's Dockerfiles, which build
# from the repo root): the stub has no path dependency on the rest of the monorepo.
#
#   docker build -f apps/screamingface-engine/deploy/kind/aigw-stub/Dockerfile \
#       -t aigw-stub:kind apps/screamingface-engine/deploy/kind/aigw-stub
FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY main.py ./main.py
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
