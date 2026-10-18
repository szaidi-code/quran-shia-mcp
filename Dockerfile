FROM python:3.11-slim

WORKDIR /app

# Copy server, builder, Jawadi loader, documentation portal, Tanzil data, and pre-indexed database
COPY server.py builder.py jawadi_loader.py index.html quran_shia.db ./
COPY data/ ./data/

ENV HOST=0.0.0.0
ENV PORT=8080
ENV DB_PATH=/app/quran_shia.db

EXPOSE 8080

CMD ["python3", "server.py"]
