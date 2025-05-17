# UltiUI

A web-based Human Machine Interface (HMI) for Ultimaker S3 printers.

https://github.com/user-attachments/assets/75450c58-1b0a-4e92-afc2-a5142318a020

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


