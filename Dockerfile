FROM python:3.11-slim

WORKDIR /app

# Copy server, builder, and pre-indexed database
COPY server.py builder.py quran_shia.db ./

ENV HOST=0.0.0.0
ENV PORT=8080
ENV DB_PATH=/app/quran_shia.db

EXPOSE 8080

CMD ["python3", "server.py"]
