FROM python:3.11-slim

# Verilator and Yosys are the real verifiers for the RTL domain.
# z3-solver's Python wheel bundles the Z3 binary, so no apt package is needed for Logic.
RUN apt-get update && apt-get install -y --no-install-recommends \
    verilator \
    yosys \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/trajectories

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
