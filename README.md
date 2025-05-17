# UltiUI

A web-based Human Machine Interface (HMI) for Ultimaker S3 printers.

Get help - https://discord.gg/jwdMU3t6uU
## Enabling Developer Mode for This Application

To allow this application to function correctly, please enable Developer Mode on your printer. This grants access to the API interface the application uses to communicate.

**(Please Note):** Activating Developer Mode enables LAN access to your system and might have security implications if your printer is WAN facing. It's best to enable it only when needed for specific applications such as UltiUI.

You can find the Developer Mode option within your printer's settings under: Advanced Settings.

## Setup
https://github.com/user-attachments/assets/75450c58-1b0a-4e92-afc2-a5142318a020

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
http://localhost:8081
```

## Configuration
The printer IP address can be configured through the web interface. The configuration is stored in a `.env` file. 


