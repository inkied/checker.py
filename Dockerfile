# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all app files
COPY . .

# Expose port (FastAPI default)
EXPOSE 8000

# Run the FastAPI app with Uvicorn
CMD ["uvicorn", "your_script_filename:app", "--host", "0.0.0.0", "--port", "8000"]
