# UltiUI

A web-based Human Machine Interface (HMI) for Ultimaker S3 printers.

## Features (Planned)
- Printer IP address configuration
- Camera feed streaming
- Printer state and information display
- Build job statistics
- Authentication system for advanced features

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Linux/Mac
# or
.\venv\Scripts\activate  # On Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the server:
```bash
python src/main.py
```

4. Open your web browser and navigate to:
```
http://localhost:8080
```

## Configuration
The printer IP address can be configured through the web interface. The configuration is stored in a `.env` file. 