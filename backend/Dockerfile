FROM python:3.11-slim

WORKDIR /app

# mediapipe/opencv 런타임에 필요한 시스템 라이브러리(libGL, GLib 등)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 퍼스널컬러/피부 학습 모델(EfficientNet) 추론용 PyTorch(CPU 전용, 용량 최소화).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

