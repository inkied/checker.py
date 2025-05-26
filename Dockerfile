FROM python:3.12-slim

# Install system deps for building wheels
RUN apt-get update && apt-get install -y build-essential libssl-dev libffi-dev python3-dev

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "checker:app", "--host", "0.0.0.0", "--port", "8000"]
