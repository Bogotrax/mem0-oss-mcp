FROM python:3.12-slim

WORKDIR /app
RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY auth.py manage.py mcp_server.py smoke_test.py ./

EXPOSE 8000
CMD ["python", "mcp_server.py"]