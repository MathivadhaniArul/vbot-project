FROM python:3.11

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    rustc \
    cargo \
    git

COPY requirements.txt .

RUN pip install --upgrade pip setuptools==69.5.1 wheel

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]