FROM python:3.11-slim

WORKDIR /app

# mediapipe/opencv 런타임에 필요한 시스템 라이브러리(libGL, GLib 등)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 퍼스널컬러/피부/네일 모델(EfficientNet·YOLOv8) 추론용 PyTorch(CPU 전용).
# ⚠️ requirements.txt **보다 먼저** 깔아야 한다. ultralytics 가 torch 를 요구하는데, 순서가
# 뒤바뀌면 pip 가 PyPI 기본 torch(CUDA 빌드)를 끌어와 nvidia-*(2.7GB)+triton(0.7GB)이
# 이미지에 남는다(실측: 3.23GB → 10.2GB). 먼저 깔면 요구사항이 이미 충족돼 CUDA 를 받지 않는다.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

