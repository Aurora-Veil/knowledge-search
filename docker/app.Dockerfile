# app & encoder

FROM python:3.12-slim AS pybase

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./

FROM pybase AS app

RUN grep -v 'encoder-only' requirements.txt > /tmp/api-requirements.txt \
 && pip install --no-cache-dir -r /tmp/api-requirements.txt

COPY app/ ./app/
COPY embedding/ ./embedding/
COPY static/ ./static/
COPY mapping/ ./mapping/

# 只放结构初始化，灌数脚本不进镜像
COPY scripts/init_es_auth.py scripts/init_es_structure.py ./scripts/

EXPOSE 8000

# 单进程默认值
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM pybase AS encoder

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu126 \
 && pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y triton nvidia-nvtx-cu12

COPY embedding/ ./embedding/

EXPOSE 8020

CMD ["python", "-m", "embedding.server"]
