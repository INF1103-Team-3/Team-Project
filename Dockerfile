FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY data/ ./data/
COPY prompts/ ./prompts/
CMD ["python", "main.py"]
